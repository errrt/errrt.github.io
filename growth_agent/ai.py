import json
import os

from .http import request_json


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
        "hypotheses": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
        "opportunities": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
    },
    "required": ["summary", "observations", "hypotheses", "opportunities"],
    "additionalProperties": False,
}

SAFE_CONTENT = {
    "summary": "Chrome Web Store公式API v2の取得範囲と欠損状態を区別して成長指標を評価します。",
    "observations": "Chrome Web Store指標は公式API v2の取得状態とobserved_days/expected_daysに基づき評価します。",
    "hypotheses": "欠損・pendingがある期間は原因を断定せず、次回取得で補完状況を確認します。",
    "opportunities": "公式API v2の取得を継続し、部分集計は取得日数と欠損状態を併記して比較します。",
}


def _max_output_tokens():
    try:
        configured = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "4000"))
    except ValueError:
        configured = 4000
    return max(1000, min(configured, 8000))


def _diagnostics(payload):
    details = payload.get("incomplete_details") or {}
    return {
        "response_id": payload.get("id"),
        "model": payload.get("model"),
        "response_status": payload.get("status"),
        "incomplete_reason": details.get("reason"),
        "usage": payload.get("usage"),
    }


def _failure(message, diagnostics=None):
    return {
        "status": "error",
        "error": message,
        "result": None,
        "fallback": "rule_based",
        "diagnostics": diagnostics or {},
    }


def _validate_result(result):
    if not isinstance(result, dict) or set(result) != set(ANALYSIS_SCHEMA["required"]):
        raise ValueError("Structured output did not contain the exact required fields")
    if not isinstance(result["summary"], str):
        raise ValueError("Structured output summary was not a string")
    for key in ("observations", "hypotheses", "opportunities"):
        values = result[key]
        if not isinstance(values, list) or not 1 <= len(values) <= 3:
            raise ValueError(f"Structured output {key} must contain 1 to 3 items")
        if not all(isinstance(value, str) for value in values):
            raise ValueError(f"Structured output {key} contained a non-string item")


def _healthy_cws_products(snapshot):
    stores = (snapshot.get("sources") or {}).get("chrome_web_store") or {}
    return {
        product
        for product, source in stores.items()
        if source.get("status") in ("ok", "partial")
        and (source.get("metrics") or {}).get("data_source") == "chrome_web_store_api_v2"
    }


def _cws_api_healthy(snapshot):
    return bool(_healthy_cws_products(snapshot))


def _contains_any(text, phrases):
    return any(phrase in text for phrase in phrases)


def _mentioned_cws_products(text, products):
    normalized = " ".join(text.lower().split())
    mentioned = set()
    for product in products:
        aliases = {product.lower(), product.lower().replace("-", " "), product.lower().replace("-", "")}
        if any(alias in normalized for alias in aliases):
            mentioned.add(product)
    return mentioned


def _content_issue(text, healthy_products, all_products):
    if not healthy_products:
        return None
    normalized = " ".join(text.lower().split())
    mentioned = _mentioned_cws_products(normalized, all_products)
    if mentioned and mentioned.isdisjoint(healthy_products):
        return None

    csv_action = "csv" in normalized and _contains_any(normalized, (
        "定期取得", "定期的に取得", "アップロード", "投入", "インポート",
        "download", "upload", "import", "periodically export", "periodic export",
    ))
    csv_safe = _contains_any(normalized, (
        "csv取得は不要", "csvの取得は不要", "csv投入は不要", "csvを投入しない",
        "csvは不要", "csv import is not required", "do not import csv",
    )) or (
        _contains_any(normalized, ("api障害時", "api失敗時", "apiが失敗", "api failure", "api outage"))
        and _contains_any(normalized, ("フォールバック", "fallback"))
    )
    if csv_action and not csv_safe:
        return "unnecessary_csv_workflow"

    scraping_action = _contains_any(normalized, ("スクレイピング", "scraping", "scrape")) and _contains_any(
        normalized, ("導入", "実行", "取得", "再開", "use ", "enable", "implement")
    )
    scraping_safe = _contains_any(normalized, (
        "スクレイピングは廃止", "スクレイピングは不要", "スクレイピングを行わない",
        "scraping is removed", "scraping is not required", "do not scrape",
    ))
    if scraping_action and not scraping_safe:
        return "public_listing_scraping"

    cws_context = _contains_any(normalized, ("chrome web store", "chromewebstore", "cws", "公式api", "store api"))
    auth_action = _contains_any(normalized, (
        "api再接続", "apiの再接続", "認証再設定", "認証の再設定", "トークン再設定",
        "reconnect", "reauthenticate", "reconfigure authentication",
    ))
    auth_safe = _contains_any(normalized, ("不要", "必要ない", "行わない", "not required", "do not"))
    if cws_context and auth_action and not auth_safe:
        return "unnecessary_api_reconfiguration"

    user_metric = _contains_any(normalized, ("users", "users-7d", "active users", "アクティブユーザー"))
    public_display = _contains_any(normalized, ("公開表示", "公開ストア", "公開カウンタ", "public listing", "publicly displayed"))
    public_safe = _contains_any(normalized, (
        "公開表示ではない", "公開指標ではない", "公開ストア表示指標ではない",
        "公開ストア上の表示指標ではない", "not a public", "is not public",
    ))
    if user_metric and public_display and not public_safe:
        return "users_misclassified_as_public_listing"

    retention = _contains_any(normalized, ("継続率", "離脱率", "retention", "churn"))
    installs = "installs" in normalized or "インストール数" in normalized
    calculation = _contains_any(normalized, ("算出", "計算", "比較", "割", "/", "%", " rate"))
    inference_safe = _contains_any(normalized, (
        "算出しない", "計算しない", "比較しない", "推定しない", "算出できない",
        "must not", "do not", "cannot calculate", "not comparable",
    ))
    if retention and installs and user_metric and calculation and not inference_safe:
        return "unsupported_retention_inference"
    return None


def _validate_content(result, snapshot):
    stores = (snapshot.get("sources") or {}).get("chrome_web_store") or {}
    all_products = set(stores)
    healthy_products = _healthy_cws_products(snapshot)
    api_healthy = _cws_api_healthy(snapshot)
    if not api_healthy:
        return result, {
            "status": "not_applicable",
            "api_v2_healthy": False,
            "healthy_products": [],
            "removed_count": 0,
        }

    sanitized = {key: (list(value) if isinstance(value, list) else value) for key, value in result.items()}
    removed = []
    summary_issue = _content_issue(sanitized["summary"], healthy_products, all_products)
    if summary_issue:
        sanitized["summary"] = SAFE_CONTENT["summary"]
        removed.append({"field": "summary", "reason": summary_issue})

    fallback_fields = []
    for field in ("observations", "hypotheses", "opportunities"):
        kept = []
        for item in sanitized[field]:
            issue = _content_issue(item, healthy_products, all_products)
            if issue:
                removed.append({"field": field, "reason": issue})
            else:
                kept.append(item)
        if not kept:
            kept = [SAFE_CONTENT[field]]
            fallback_fields.append(field)
        sanitized[field] = kept

    _validate_result(sanitized)
    return sanitized, {
        "status": "sanitized" if removed else "passed",
        "api_v2_healthy": True,
        "healthy_products": sorted(healthy_products),
        "removed_count": len(removed),
        "removed": removed,
        "fallback_fields": fallback_fields,
    }


def _extract_output_text(payload):
    refusals = [
        content
        for item in payload.get("output", [])
        for content in item.get("content", [])
        if content.get("type") == "refusal"
    ]
    if refusals:
        raise ValueError("OpenAI refused the structured analysis request")

    texts = [
        content.get("text")
        for item in payload.get("output", [])
        if item.get("type") == "message"
        for content in item.get("content", [])
        if content.get("type") == "output_text" and isinstance(content.get("text"), str)
    ]
    if len(texts) != 1:
        raise ValueError(f"Expected exactly one output_text item, received {len(texts)}")
    return texts[0]


def analyze(snapshot, history):
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        return {
            "status": "missing",
            "error": "OPENAI_API_KEY and OPENAI_MODEL are required",
            "result": None,
            "fallback": "rule_based",
            "diagnostics": {},
        }

    context = {
        "data_contract": {
            "chrome_web_store": {
                "primary_source": "Chrome Web Store API v2 queryMetrics (official)",
                "csv_role": "Fallback only when the official API request fails",
                "public_listing_scraping": "Removed; no public store page scraping is used",
                "partial_periods": "Use observed_days/expected_days and never present partial totals as complete periods",
                "missing_values": "null/missing/pending/failed are unknown states, never numeric zero",
                "active_users": "users and users-7d are active-user metrics, not total installed users",
                "recommendation_guard": (
                    "When data_source is chrome_web_store_api_v2 and collection status is ok/partial, do not recommend "
                    "CSV import, API reconnection, authentication reconfiguration, or public listing scraping"
                ),
                "inference_guard": (
                    "Do not estimate churn, retention, conversion, or causal effects unless comparable observed metrics "
                    "directly support it. Never compare or divide installs by users/users-7d to calculate retention; "
                    "these metrics have different definitions and populations"
                ),
            }
        },
        "today": snapshot,
        "history": history[-30:],
    }
    body = {
        "model": model,
        "instructions": (
            "個人開発アプリの日次成長snapshotを日本語で分析してください。観測事実と仮説を明確に分離し、"
            "欠損をゼロとして扱わず、因果関係を断定しないでください。各配列は重要度順に最大3件、"
            "各項目は簡潔にしてください。入力のdata_contractを現在の実装仕様として必ず優先し、"
            "古いhistoryに残る過去の収集方式や改善提案を現在も必要なものとして扱わないでください。"
            "installsとusers/users-7dを直接比較して継続率や離脱率を算出しないでください。"
        ),
        "input": json.dumps(context, ensure_ascii=False),
        "max_output_tokens": _max_output_tokens(),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "growth_analysis",
                "strict": True,
                "schema": ANALYSIS_SCHEMA,
            }
        },
    }
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "minimal").strip()
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}

    try:
        payload = request_json(
            "https://api.openai.com/v1/responses",
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body=body,
        )
    except Exception as error:
        return _failure(f"OpenAI request failed: {error}")

    diagnostics = _diagnostics(payload)
    if payload.get("status") != "completed":
        status = payload.get("status") or "unknown"
        reason = diagnostics["incomplete_reason"] or "not_provided"
        return _failure(f"OpenAI response was not completed: status={status}, reason={reason}", diagnostics)

    try:
        text = _extract_output_text(payload)
        try:
            result = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Structured output JSON decode failed at char {error.pos}; output_chars={len(text)}"
            ) from error
        _validate_result(result)
        result, content_validation = _validate_content(result, snapshot)
        diagnostics["content_validation"] = content_validation
    except Exception as error:
        return _failure(str(error), diagnostics)

    return {
        "status": "ok",
        "error": None,
        "result": result,
        "fallback": None,
        "diagnostics": diagnostics,
    }


def log_line(analysis):
    diagnostics = analysis.get("diagnostics") or {}
    usage = diagnostics.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    fields = [
        f"status={analysis.get('status', 'unknown')}",
        f"response_id={diagnostics.get('response_id') or 'n/a'}",
        f"model={diagnostics.get('model') or 'n/a'}",
        f"response_status={diagnostics.get('response_status') or 'n/a'}",
        f"incomplete_reason={diagnostics.get('incomplete_reason') or 'n/a'}",
        f"input_tokens={usage.get('input_tokens', 'n/a')}",
        f"output_tokens={usage.get('output_tokens', 'n/a')}",
        f"reasoning_tokens={details.get('reasoning_tokens', 'n/a')}",
        f"fallback={analysis.get('fallback') or 'none'}",
        f"content_validation={(diagnostics.get('content_validation') or {}).get('status', 'n/a')}",
    ]
    if analysis.get("error"):
        fields.append(f"error={analysis['error']}")
    return "AI analysis: " + " ".join(fields)
