# errrt

The official home of errrt — tiny software for everyday annoyances.

This is a dependency-free static site made for GitHub Pages. GitHub publishes the repository root from `main`.

## File structure

```text
index.html          # Page and SEO metadata
.nojekyll           # Disables Jekyll processing on GitHub Pages
dist/
├── favicon.svg
├── og-image.png
├── og-image.svg
├── site-config.js  # Product and social URLs
└── styles.css
scripts/
├── build.mjs       # Lightweight validation
└── dev.mjs         # Local static server
growth_agent/        # Daily collectors, analysis, and Markdown report
growth-agent.json    # Non-secret source configuration
go/                  # Same-origin outbound click redirect pages
.github/workflows/daily-growth.yml
```

## Local development

No dependency installation or compilation is required.

```sh
npm run dev
```

Open `http://localhost:4173`. Run the same validation used in CI with:

```sh
npm run build
```

## Update links

All product, X, and GitHub URLs live in `dist/site-config.js`. Replace the empty strings in `LINK_TARGETS`; no HTML editing is needed. Empty URLs are displayed as unavailable links.

## Deploy to GitHub Pages

1. Push this project to the `main` branch of `errrt/errrt.github.io`.
2. Open the repository's **Settings → Pages**.
3. Under **Build and deployment**, select **Deploy from a branch**.
4. Select the `main` branch and `/ (root)`, then save.

The site is published automatically after every push to `main`. No build action or generated branch is needed.

## Analytics

Cloudflare Web Analytics is loaded once from `index.html` with the beacon token currently issued for `errrt.github.io`. The module script is placed before `</body>` so it does not block rendering or alter SEO metadata. Cloudflare's public beacon token and the GraphQL `siteTag` identifier are separate values for this site: keep the beacon token aligned with the installation snippet, and keep `growth-agent.json` aligned with the `siteTag` shown in the Web Analytics overview URL.

PhraseCrate, Tab Parcel, GitHub, and X links use same-origin `/go/<key>/index.html` redirect pages. Those pages load the same Cloudflare beacon before forwarding to the external destination, so daily link clicks can be queried by `requestPath` without adding another analytics vendor. A destination that has not been confirmed remains disabled instead of being guessed.

## Daily Growth Agent

GitHub Actions starts the report at 04:30 JST every day so it can finish before 05:00. The workflow stores two 90-day artifacts:

- `growth-report-<run id>`: `snapshot.json` and the Japanese `report.md`
- `growth-history`: rolling daily snapshots used for previous-day, 7-day, and 30-day comparisons

The Markdown report is also written to the workflow's **Summary** page. Missing and failed values remain `null`/`—`; they are never converted to zero. In particular, an empty Cloudflare GraphQL result is recorded as missing with the queried UTC window, not as zero traffic. A deterministic report is always generated, while OpenAI analysis is optional. The Summary includes an explicit AI analysis status and states when the report used the rule-based fallback.

Run it locally with yesterday's JST date:

```sh
python -m growth_agent.main
```

Or reproduce a specific day:

```sh
python -m growth_agent.main --date 2026-10-23
```

### Required GitHub configuration

Open **Settings → Secrets and variables → Actions**. Do not commit any token.

| Name | Kind | Required | Purpose |
|---|---|---:|---|
| `CLOUDFLARE_API_TOKEN` | Secret | Yes for LP analytics | Cloudflare token restricted to **Account Analytics: Read** for the errrt account |
| `GROWTH_GITHUB_TOKEN` | Secret | Only for private repos or traffic | Fine-grained token restricted to the configured repositories; public metadata works anonymously and the built-in `GITHUB_TOKEN` is used in Actions |
| `X_BEARER_TOKEN` | Secret | Only after paid X API approval | Reads posts and public metrics; set an X developer spend limit first |
| `OPENAI_API_KEY` | Secret | Optional | Adds AI observations/hypotheses to the deterministic report |
| `OPENAI_MODEL` | Actions variable | Optional | Model used when `OPENAI_API_KEY` is enabled |
| `GCP_WIF_PROVIDER` | Actions variable | Yes for store metrics | Full Workload Identity Provider resource name |
| `GCP_CWS_SERVICE_ACCOUNT` | Actions variable | Yes for store metrics | Existing service account email registered in the Developer Dashboard |
| `CWS_PUBLISHER_ID` | Actions variable | Yes for store metrics | Chrome Web Store publisher ID |

The Cloudflare Account ID and Web Analytics Site Tag are non-secret identifiers and are already in `growth-agent.json`. `CLOUDFLARE_ACCOUNT_ID` may be supplied as a Secret to override the file. The configured API token must not have write permissions.

The errrt X account is configured as `@errrt0dev`. Its public link is measured through `go/x/index.html`. X API reads are usage-priced, so performance collection remains inactive until paid API access and a spend limit are explicitly approved.

### Chrome Web Store data

The Daily Growth workflow uses GitHub OIDC → Google Cloud Workload Identity Federation → the existing service account. It requests only the `chromewebstore.readonly` scope and calls the official Chrome Web Store API v2 `queryMetrics` method. No JSON key is stored.

The collector uses this order:

1. Official API v2 for `installs`, `uninstalls`, `impressions`, `page-views`, `users`, and `users-7d`, plus `install-source` and `utm-source` where the API returns them.
2. A normalized official CSV at `imports/chrome-web-store/<slug>.csv` only when API authentication or the request fails.

Every run re-queries the preceding 30 dates so delayed data can replace earlier pending values. Raw API responses and normalized daily rows are saved under `growth-history/chrome-web-store/` and copied into the report artifact. A returned numeric zero is stored as `observed`; absent metrics are `null` with `missing`, and dates after the latest returned API row are `pending`. The API exposes no explicit finalization flag, so `pending` is an agent-side state, not a Google guarantee.

The CSV fallback accepts:

```csv
date,installs,uninstalls,users,users_7d,impressions,page_views,acquisition_source
2026-10-23,1,0,4,3,20,5,direct
```

`users` and `users-7d` are active-user metrics. They are never presented as total installed users. The public store page is not scraped.
The report labels `installs / page-views` as a reference ratio, not a strict user conversion rate. Source-dimension totals always include observed-day coverage, so partial responses are not presented as complete 30-day results.

### Cost and safety controls

- Cloudflare Web Analytics, Chrome Web Store API v2, Workload Identity Federation, and GitHub Actions within account limits add no new fixed paid service for this setup.
- OpenAI uses Structured Outputs with minimal reasoning effort and is capped to 4,000 output tokens per run (8,000 hard cap in code). The response must be `completed` before JSON is parsed.
- X is disabled until the username, paid access, and spend limit are explicitly approved.
- The workflow does not create Issues/PRs, merge, deploy, or publish X posts. It only prepares and reports recommended actions.
- Re-running the same date overwrites that date's snapshot, making collection idempotent.

See [the Phase 1 investigation](docs/growth-agent-phase-1.md) for metric availability, permissions, limitations, and official references.

## Custom domain

1. Open **Settings → Pages → Custom domain** and enter the domain.
2. Configure the required DNS record with your DNS provider.
   - For a subdomain such as `www.example.com`, create a `CNAME` pointing to `<user-or-org>.github.io` without a repository path.
   - For an apex domain such as `example.com`, use the current `A`, `AAAA`, `ALIAS`, or `ANAME` values from GitHub's documentation.
3. After DNS is active, enable **Enforce HTTPS** in the Pages settings.
4. Update the canonical URL, `og:url`, and Open Graph image URLs in `index.html` to the custom domain.

GitHub creates a `CNAME` file when a custom domain is saved for a branch-published site. Pull that commit before making later changes.

- [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [GitHub Pages custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site)
