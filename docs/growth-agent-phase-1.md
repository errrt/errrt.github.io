# errrt Growth Agent — Phase 1調査結果

調査日: 2026-10-23

## 現在確認できた対象

| 対象 | 公開URL / ID | 確認結果 |
|---|---|---|
| errrt LP | https://errrt.github.io/ | `errrt/errrt.github.io` のGitHub Pages。Cloudflare Web Analyticsの正式なSite Tag `1709ef2ee75e4ed88b82a65361e0588a`へ修正済み |
| PhraseCrate | Chrome Web Store item `gngjinfejkkiflogppaadaandlenomcd` | LP設定から確認 |
| Tab Parcel | Chrome Web Store item `pohjmphoidcblbneaeabbpjhcjjlbhke` | LP設定から確認 |
| X | 未設定 | LPのX URLが空。X検索でもブランドアカウントを特定できず、現在ログイン中のアカウントは`@koeapp`。正確なユーザー名の確認が必要 |
| GitHub | `errrt/errrt.github.io`, `errrt/tab-dump-privacy` | LPはcheckoutのremoteから確認。後者は公開repoの最新commitがTab Parcel Pro privacy policyであることを確認 |

LPの外部リンクは`/go/<key>/index.html`を経由する。同じCloudflare Web Analyticsビーコンでこの中継ページを計測し、GraphQLの`requestPath`からリンク別クリック数を取得する。Cloudflare Web Analyticsがcustom eventsを提供しないため、非公式イベントAPIや別の分析サービスは追加していない。

GitHubの公開APIで確認できた公開repoは`archlint`、`errrt.github.io`、`linkshape-privacy`、`tab-dump-privacy`、`tiny-expander`の5件。サインイン済みプロフィールには公開・非公開あわせて18 repoが表示された。`phrase`で一致するrepoはなく、PhraseCrate本体repoは特定できなかった。名前からの推測で別repoを紐付けてはいない。GitHubプロフィールの`twitter_username`も未設定だった。

## 取得可否・権限・費用

| データ源 | 取得できる指標 | 取得できない／制約 | 必要な認証 | 追加費用 | 推奨方法 |
|---|---|---|---|---|---|
| Cloudflare Web Analytics | PV (`count`)、訪問 (`sum.visits`)、流入元、日次系列 | Web Analyticsの`visits`は厳密なUUとは同義でない。7日超はサンプリングされ得る | Account Analytics: ReadのAPI Token、Account ID、Site Tag | Web Analytics自体は無料 | GraphQL `rumPageloadEventsAdaptiveGroups`を毎日保存 |
| Chrome Web Store | 公式ダッシュボードでinstall/uninstall、impression、users、CSV export。公開listingの表示users・評価・評価件数 | 公開・管理APIは日次統計／レビュー取得APIではない。公式の自動CSV export APIは確認できない。公開usersは丸められる場合がある | Publisher dashboard権限。GA4を使うならGoogle認証 | 基本無料 | 公式CSVを優先し、未投入日は公開listingをpartialデータとして補助利用 |
| X API | 投稿、public metrics（impression、like、repost、reply等）。own postの非公開指標はuser-context認証 | 読み取りは従量課金。非公開／organic metricsはOAuth user contextが必要 | Developer app、Bearer Token。詳細指標はOAuth 1.0aまたはOAuth 2.0 user context | 2026-10-23時点でPost read $0.005/resource、User read $0.010/resource。価格変更あり | 承認後、少量の日次取得＋Developer Consoleのspend limit |
| GitHub | commits、issues、PR、stars。traffic views/clones/referrersは直近14日 | trafficはwrite accessが必要で14日rolling。`GITHUB_TOKEN`は原則そのrepoのみ | 現repoはActions token。他repoはfine-grained PATまたはGitHub App | 通常無料 | 毎日snapshotして14日制限を補う |
| OpenAI API | Responses APIによるレポート分析 | ChatGPTの会話へ任意のActions結果を直接投稿する一般公開APIは確認できない | OpenAI API key | model token従量課金 | まず決定論的分析。API導入時は1runの出力上限を設定 |

## ChatGPT配信

正式な選択肢は、ChatGPTのScheduled Tasks、またはWork向けMCP Events。GitHub ActionsのMarkdownをChatGPT会話に直接pushする単純な公開APIとしては扱わない。MVPはGitHub Actions SummaryとArtifactを正本にし、通知が必要ならGitHub Issue、メール、Slack等を別途選定する。

## 必要な設定

1. `gh auth login -h github.com`でローカルGitHub CLI認証を復旧する。PhraseCrate本体repoが別名または別ownerなら、その正確なrepo名を`growth-agent.json`へ追加する。
2. GitHub Actions Secretsに`CLOUDFLARE_API_TOKEN`を追加する。Account IDとSite Tagは非機密設定として`growth-agent.json`に設定済み。
3. Xのユーザー名を`growth-agent.json`に設定する。有料のX API credit購入は事前承認後に行う。
4. 複数repoを読む場合は、対象repoだけに絞ったfine-grained PATを`GROWTH_GITHUB_TOKEN`として追加する。trafficにはAdministration: Readが必要。
5. 正確な日次獲得指標が必要なら、Chrome Web Storeの公式CSVを`imports/chrome-web-store/<slug>.csv`へ配置する。列名は`date,installs,uninstalls,users,impressions,rating,reviews,acquisition_source`へ正規化する。未投入日は公開listingのusers・評価のみ自動取得する。
6. AI分析を有効化する場合だけ`OPENAI_API_KEY` Secretと`OPENAI_MODEL` Actions Variableを追加する。1実行の出力は最大1,200 tokens（コード上限2,000）に制限している。

## 実装方針

Python標準ライブラリだけで構成し、GitHub Actionsを毎日04:30 JST（19:30 UTC）に開始して05:00までの完了を目指す。取得失敗は`null`相当のmissing/errorとして保存し、ゼロには変換しない。snapshotと日本語Markdown reportは90日Artifactとして保存し、前回Artifactから履歴を復元する。同じ提案はfingerprintを使って30 snapshotの間抑制する。OpenAIはStructured Outputsを使う任意機能で、観測事実と仮説を分離する。Issues、PR、X投稿などの外部書込みは初期版では無効。

## 参照した公式資料

- Cloudflare GraphQL Analytics API: https://developers.cloudflare.com/analytics/graphql-api/
- Cloudflare Web Analytics metrics / dimensions: https://developers.cloudflare.com/web-analytics/data-metrics/high-level-metrics/ / https://developers.cloudflare.com/web-analytics/data-metrics/dimensions/
- Chrome Web Store metrics: https://developer.chrome.com/docs/webstore/metrics
- Chrome Web Store API: https://developer.chrome.com/docs/webstore/api
- X metrics / pricing: https://docs.x.com/x-api/fundamentals/metrics / https://docs.x.com/x-api/getting-started/pricing
- GitHub traffic API: https://docs.github.com/en/rest/metrics/traffic
- OpenAI Scheduled Tasks / MCP Events: https://learn.chatgpt.com/docs/automations / https://developers.openai.com/plugins/build/mcp-events
- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses
