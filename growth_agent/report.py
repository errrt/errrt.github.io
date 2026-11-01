import hashlib
import json


def _metric(source, key):
    if not source or source.get("status") not in ("ok", "partial"):
        return None
    return (source.get("metrics") or {}).get(key)


def _fmt(value, percent=False):
    if value is None:
        return "—"
    if percent:
        return f"{value:.1%}"
    return f"{value:,.0f}" if isinstance(value, (int, float)) else str(value)


def _fingerprint(action):
    raw = "|".join(action[key] for key in ("product", "problem", "recommendation"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _history_values(history, source_name, metric, limit):
    values = []
    for snapshot in history[-limit:]:
        value = _metric(snapshot.get("sources", {}).get(source_name), metric)
        if isinstance(value, (int, float)):
            values.append(value)
    return values


def _store_history_values(history, slug, metric, limit):
    values = []
    for snapshot in history[-limit:]:
        source = snapshot.get("sources", {}).get("chrome_web_store", {}).get(slug)
        value = _metric(source, metric)
        if isinstance(value, (int, float)):
            values.append(value)
    return values


def _comparison(label, current, values):
    if current is None or not values:
        return f"- {label}: 比較不可（現在値または過去データが不足）"
    baseline = sum(values) / len(values)
    if baseline == 0:
        return f"- {label}: {_fmt(current)}（比較対象平均は0）"
    delta = (current - baseline) / baseline
    absolute = current - baseline
    return f"- {label}: {_fmt(current)}（直近{len(values)}日平均 {_fmt(baseline)} 比 {absolute:+,.0f} / {delta:+.1%}）"


def _period_cell(source, period, metric):
    value = (((source.get("metrics") or {}).get("periods") or {}).get(period) or {}).get(metric) or {}
    if value.get("value") is None:
        return f"— ({value.get('state', 'missing')})"
    coverage = "" if value.get("state") == "observed" else f" ({value.get('observed_days', 0)}/{value.get('expected_days', 0)}日)"
    return f"{_fmt(value['value'])}{coverage}"


def _active_cell(source, metric):
    value = (((source.get("metrics") or {}).get("active_users") or {}).get(metric) or {})
    if value.get("value") is None:
        return "—"
    return f"{_fmt(value['value'])} ({value.get('date')})"


def _active_trend(source, metric):
    value = (((source.get("metrics") or {}).get("active_users") or {}).get(metric) or {})
    trend = value.get("trend_7d") or []
    return " → ".join(f"{row['date'][5:]}:{_fmt(row.get('value'))}" for row in trend) or "—"


def _one_line(value):
    return " ".join(str(value).split())


def build_actions(snapshot, history):
    actions = []
    cf = snapshot["sources"]["cloudflare"]
    if cf["status"] != "ok":
        actions.append({
            "product": "errrt LP", "problem": "Cloudflareデータを取得できていない",
            "evidence": cf.get("error") or "collector error",
            "recommendation": "Account Analytics: Read権限のAPI TokenをGitHub Actions Secretsへ登録し、workflowを再実行する。",
            "expected_effect": "LP流入の基準値を確立する。次回snapshotでPV・訪問・流入元が欠損でないことを確認する。", "priority": "P0",
        })

    stores = snapshot["sources"]["chrome_web_store"]
    missing_stores = [name for name, value in stores.items() if value["status"] not in ("ok", "partial")]
    if missing_stores:
        actions.append({
            "product": ", ".join(missing_stores), "problem": "Chrome Web Store指標を取得できていない",
            "evidence": "公式APIとCSVフォールバックの両方から利用可能なデータを取得できなかった。",
            "recommendation": "WIFのVariables・サービスアカウント権限・Chrome Web Store readonly API応答を確認し、必要なら公式CSVをimports/chrome-web-store/へ配置する。",
            "expected_effect": "install・impression推移を測定可能にする。次回レポートのKPI行が欠損でないことを確認する。", "priority": "P0",
        })

    x = snapshot["sources"]["x"]
    if x["status"] == "ok" and _metric(x, "posts") == 0:
        actions.append({
            "product": "errrt X", "problem": "前日にオリジナル投稿がなかった", "evidence": "投稿数 = 0",
            "recommendation": "ストアまたはLPへの計測可能なリンクを1つだけ含むプロダクト投稿案を作る。公開は人間の承認後に行う。",
            "expected_effect": "測定可能な獲得接点を作る。7日間のリンク訪問とユーザー数変化で検証する。", "priority": "P1",
        })
    elif x["status"] != "ok":
        actions.append({
            "product": "errrt X", "problem": "Xの投稿別パフォーマンスを取得できていない", "evidence": x.get("error") or "collector error",
            "recommendation": "対象ユーザー名を確定し、有料X APIの採用を判断する。承認する場合のみBearer Tokenとspend limitを設定する。",
            "expected_effect": "投稿別の表示・反応を比較可能にする。次回レポートにimpressionとengagement rateが入ることを確認する。", "priority": "P1",
        })

    previous = {action.get("fingerprint") for item in history[-30:] for action in item.get("actions", [])}
    output = []
    for action in actions:
        action["fingerprint"] = _fingerprint(action)
        if action["fingerprint"] not in previous:
            output.append(action)
    return output[:3]


def _collection_notes(snapshot):
    notes = []
    for name, source in snapshot["sources"].items():
        if name == "chrome_web_store":
            for slug, value in source.items():
                if value["status"] not in ("ok", "partial"):
                    notes.append(f"{name}/{slug}: {_one_line(value.get('error'))}")
                elif _metric(value, "limitations"):
                    notes.append(f"{name}/{slug}: {_one_line(_metric(value, 'limitations'))}")
        elif name == "github" and source.get("status") == "ok":
            notes.extend(
                f"github/{repo}: {_one_line(value.get('error'))}"
                for repo, value in (source.get("metrics") or {}).items()
                if value.get("status") == "partial"
            )
        elif source.get("status") != "ok":
            notes.append(f"{name}: {_one_line(source.get('error'))}")
    analysis = snapshot.get("analysis", {})
    if analysis.get("status") in ("missing", "error"):
        notes.append(f"openai: {_one_line(analysis.get('error'))}")
    return notes


def _previous_action_result(action, snapshot):
    product = action.get("product", "対象不明")
    if "LP" in product:
        kpi = f"現在のLP PV = {_fmt(_metric(snapshot['sources']['cloudflare'], 'page_views'))}"
    elif "X" in product:
        kpi = f"現在の投稿数 = {_fmt(_metric(snapshot['sources']['x'], 'posts'))}"
    else:
        values = []
        for slug, source in snapshot["sources"]["chrome_web_store"].items():
            if slug in product:
                values.append(f"{slug} users = {_fmt(_metric(source, 'users'))}")
        kpi = ", ".join(values) or "対応KPIを自動特定できない"
    return f"- **{product}**: {kpi}。施策の実行記録がないため、効果は評価保留（因果関係は判定しない）。"


def render(snapshot, history):
    actions = snapshot["actions"]
    cf = snapshot["sources"]["cloudflare"]
    source_groups_ok = 0
    for name, source in snapshot["sources"].items():
        if name == "chrome_web_store":
            source_groups_ok += int(any(value.get("status") in ("ok", "partial") for value in source.values()))
        else:
            source_groups_ok += int(source.get("status") in ("ok", "partial"))

    lines = [
        f"# errrt Daily Growth Report — {snapshot['date']}", "", "## Executive Summary", "",
        f"全{len(snapshot['sources'])}データソース群のうち{source_groups_ok}群から利用可能なデータを取得しました。"
        f"欠損は「—」で示し、ゼロとして扱いません。重複を除いた本日の推奨アクションは{len(actions)}件です。",
        "", "## プロダクト別KPI", "",
        "| プロダクト | PV | 訪問 | install | active users | GitHub Stars | X投稿 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    github_repos = snapshot["sources"]["github"].get("metrics") or {}
    lp_repo = github_repos.get("errrt/errrt.github.io", {})
    lines.append(
        f"| errrt LP | {_fmt(_metric(cf, 'page_views'))} | {_fmt(_metric(cf, 'visits'))} | — | — | {_fmt(_metric(lp_repo, 'stars'))} | — |"
    )
    for slug, source in snapshot["sources"]["chrome_web_store"].items():
        lines.append(
            f"| {slug} | {_fmt(_metric(source, 'page_views'))} | — | {_fmt(_metric(source, 'installs'))} | "
            f"{_active_cell(source, 'users')} | — | — |"
        )
    lines.append(f"| errrt X | — | — | — | — | — | {_fmt(_metric(snapshot['sources']['x'], 'posts'))} |")

    lines += ["", "### Chrome Web Store公式Metrics", ""]
    for slug, source in snapshot["sources"]["chrome_web_store"].items():
        lines += [
            f"#### {slug}", "",
            "| 期間 | installs | uninstalls | impressions | page views | インストール数／ストアPV（参考比率） |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        conversions = _metric(source, "conversion_rate") or {}
        for label in ("1d", "7d", "30d"):
            lines.append(
                f"| {label} | {_period_cell(source, label, 'installs')} | {_period_cell(source, label, 'uninstalls')} | "
                f"{_period_cell(source, label, 'impressions')} | {_period_cell(source, label, 'page_views')} | "
                f"{_fmt(conversions.get(label), percent=True)} |"
            )
        lines += [
            "",
            f"- Daily active users: {_active_cell(source, 'users')}（総インストールユーザー数ではありません）",
            f"- 7-day active users: {_active_cell(source, 'users_7d')}（総インストールユーザー数ではありません）",
            f"- Active users推移（取得済み直近7日）: {_active_trend(source, 'users')}",
            f"- 取得元: `{_metric(source, 'data_source') or '—'}` / 最終取得: {_metric(source, 'last_updated_at') or '—'}",
        ]
        breakdown = _metric(source, "source_breakdown_30d") or {}
        for title, key in (("install-source", "install_source"), ("UTM source", "utm_source")):
            summary = breakdown.get(key) or {}
            values = summary.get("values") or {}
            coverage = f"{summary.get('observed_days', 0)}/{summary.get('expected_days', 30)}日"
            if values:
                lines.append(f"- {title}（30日、取得 {coverage}、状態: {summary.get('state', 'missing')}）: " + ", ".join(
                    f"{name}=" + "/".join(f"{metric}:{_fmt(value)}" for metric, value in metrics.items())
                    for name, metrics in sorted(values.items())
                ))
            else:
                lines.append(f"- {title}（30日、取得 {coverage}、状態: {summary.get('state', 'missing')}）: —（API応答なし）")

    x_metrics = snapshot["sources"]["x"]
    lines += [
        "", "### Xパフォーマンス", "",
        "| 投稿数 | impressions | いいね | リポスト | 返信 | engagement rate |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {_fmt(_metric(x_metrics, 'posts'))} | {_fmt(_metric(x_metrics, 'impressions'))} | "
        f"{_fmt(_metric(x_metrics, 'likes'))} | {_fmt(_metric(x_metrics, 'reposts'))} | "
        f"{_fmt(_metric(x_metrics, 'replies'))} | {_fmt(_metric(x_metrics, 'engagement_rate'), percent=True)} |",
    ]
    post_metrics = _metric(x_metrics, "post_metrics") or []
    if post_metrics:
        lines += ["", "| Post ID | impressions | いいね | リポスト | 返信 | engagement rate |", "|---|---:|---:|---:|---:|---:|"]
        for post in post_metrics:
            lines.append(
                f"| {post.get('id', '—')} | {_fmt(post.get('impressions'))} | {_fmt(post.get('likes'))} | "
                f"{_fmt(post.get('reposts'))} | {_fmt(post.get('replies'))} | {_fmt(post.get('engagement_rate'), percent=True)} |"
            )

    lines += ["", "### LP外部リンククリック", "", "| 遷移先 | クリック |", "|---|---:|"]
    outbound_clicks = _metric(cf, "outbound_clicks") or {}
    for destination in ("phraseCrate", "tabParcel", "github", "x"):
        lines.append(f"| {destination} | {_fmt(outbound_clicks.get(destination))} |")

    lines += ["", "## 前日・直近7日・直近30日の変化", ""]
    current_pv = _metric(cf, "page_views")
    current_visits = _metric(cf, "visits")
    lines += [
        _comparison("LP PV / 前日", current_pv, _history_values(history, "cloudflare", "page_views", 1)),
        _comparison("LP PV / 7日平均", current_pv, _history_values(history, "cloudflare", "page_views", 7)),
        _comparison("LP PV / 30日平均", current_pv, _history_values(history, "cloudflare", "page_views", 30)),
        _comparison("LP訪問 / 7日平均", current_visits, _history_values(history, "cloudflare", "visits", 7)),
    ]
    for slug, source in snapshot["sources"]["chrome_web_store"].items():
        lines.append(_comparison(f"{slug} users / 前日", _metric(source, "users"), _store_history_values(history, slug, "users", 1)))

    lines += ["", "## 流入経路の分析", ""]
    referrers = _metric(cf, "referrers")
    if referrers:
        for row in referrers[:10]:
            lines.append(f"- {row.get('host') or 'direct'}: {_fmt(row.get('page_views'))} PV")
        x_pv = sum(row.get("page_views", 0) for row in referrers if row.get("host") in ("x.com", "t.co", "twitter.com"))
        lines.append(f"- X由来として識別できた流入: {_fmt(x_pv)} PV（referrerベース）")
    else:
        lines.append("- Cloudflareの流入元データがないため分析不可。")

    lines += ["", "## ボトルネック", ""]
    if _metric(cf, "visits") is None:
        lines.append("- 観測事実: LP訪問が欠損しており、流入からストア遷移までのファネルを評価できない。")
    elif not outbound_clicks:
        lines.append("- 観測事実: LP訪問は取得できたが外部リンククリックが0件または未計測。導線別転換をまだ評価できない。")
    else:
        total_clicks = sum(value for value in outbound_clicks.values() if isinstance(value, (int, float)))
        visits = _metric(cf, "visits")
        rate = total_clicks / visits if visits else None
        lines.append(f"- 観測事実: LP訪問 {_fmt(visits)} に対し外部リンククリック {_fmt(total_clicks)}（クリック/訪問 {_fmt(rate, percent=True)}）。")
    if any(_metric(value, "data_source") != "chrome_web_store_api_v2" for value in snapshot["sources"]["chrome_web_store"].values()):
        lines.append("- 計測上の制約: Chrome Web Store公式APIを取得できない製品があり、CSVフォールバックまたは欠損です。")
    if snapshot["sources"]["x"].get("status") != "ok":
        lines.append("- 計測上の制約: X投稿指標が欠損しており、投稿→LP流入の寄与を分離できない。")

    analysis = snapshot.get("analysis", {})
    diagnostics = analysis.get("diagnostics") or {}
    usage = diagnostics.get("usage") or {}
    lines += ["", "## AI分析状態", ""]
    if analysis.get("status") == "ok":
        lines.append(
            f"- 成功（Structured Outputs / model: `{diagnostics.get('model') or '不明'}` / "
            f"response: `{diagnostics.get('response_id') or '不明'}` / input tokens: {_fmt(usage.get('input_tokens'))} / "
            f"output tokens: {_fmt(usage.get('output_tokens'))}）"
        )
    else:
        lines.append(
            "- 失敗または未設定のため、ルールベース分析へフォールバックしました。"
            f"状態: `{analysis.get('status', 'unknown')}` / API状態: `{diagnostics.get('response_status') or '不明'}` / "
            f"理由: {_one_line(analysis.get('error'))}"
        )

    lines += ["", "## 重要な発見", ""]
    if analysis.get("status") == "ok":
        result = analysis["result"]
        lines += [f"**AI要約:** {result['summary']}", "", "観測事実:", ""]
        lines.extend(f"- {item}" for item in result["observations"])
        lines += ["", "仮説（因果関係の断定ではありません）:", ""]
        lines.extend(f"- {item}" for item in result["hypotheses"])
        lines += ["", "成長機会:", ""]
        lines.extend(f"- {item}" for item in result["opportunities"])
    else:
        lines.append("- AI分析は利用できませんでした。上記のKPI・流入・ボトルネックはルールベースで生成しています。")

    lines += ["", "## 前日の施策と結果", ""]
    previous_actions = history[-1].get("actions", []) if history else []
    if previous_actions:
        lines.extend(_previous_action_result(action, snapshot) for action in previous_actions)
    else:
        lines.append("- 前回snapshotに施策記録がないため評価対象なし。")

    lines += ["", "## 今日の推奨アクション（最大3件）", ""]
    if not actions:
        lines.append("新規アクションなし。直近30 snapshotと同じ提案は重複抑制しました。")
    for index, action in enumerate(actions, 1):
        lines += [
            f"### {index}. [{action['priority']}] {action['product']}", "",
            f"- 発見した問題: {action['problem']}",
            f"- 数値的根拠: {action['evidence']}",
            f"- 推奨アクション: {action['recommendation']}",
            f"- 期待効果と検証方法: {action['expected_effect']}",
            f"- 重複判定ID: `{action['fingerprint']}`", "",
        ]

    notes = _collection_notes(snapshot)
    lines += ["## 自動作成したIssues・PR", "", "なし。外部書込み・自動マージ・自動投稿は無効です。", "", "## データ取得エラー・制約", ""]
    lines.extend([f"- {note}" for note in notes] or ["- なし"])
    return "\n".join(lines) + "\n"


def load_history(path):
    snapshots = []
    if path.exists():
        for item in sorted(path.glob("*.json")):
            try:
                snapshots.append(json.loads(item.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    return snapshots
