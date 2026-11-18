# Growth data quality contract

The collector keeps provider state separate from numeric values. Missing values are never converted to zero after an authentication or request failure.

## States

- `observed`: the provider returned a value. A numeric `0` is a real zero.
- `pending`: the requested date is newer than the latest date returned by the provider.
- `missing`: the provider should have supplied the cell, but no usable observation exists.
- `failed`: the request failed after collection began.
- `unavailable`: the provider cannot supply the cell for the requested date or the metric is outside the supported collection policy.

Chrome Web Store `queryMetrics` returns one date row with sparse metric columns. A requested metric omitted from a returned, finalized date row is stored as `0` with provenance `api_sparse_zero`. A date with no row is not zero. Leading dates before the first returned date are marked `unavailable` during backfill. Dates after the latest returned date remain `pending`.

Cloudflare RUM aggregate queries return no group when no event matches. A successful empty aggregate is therefore a confirmed zero. HTTP errors, GraphQL errors, missing accounts, and missing credentials remain failures or missing configuration.

Chrome Web Store supports installs, rolling 7-day installs, uninstalls, users, rolling 7-day users, impressions, and page views. This collector does not claim total installed users, retention, or product usage. Cloudflare `unique_users` is not collected by the current query. X reads remain outside the required quality gate because the API is paid and no new paid service is allowed. GitHub traffic remains degraded until the token has repository Administration read permission.

## History safety

Normalized CWS history is merged by date and metric. A new explicit API value may correct an older value. `pending`, `missing`, and inferred sparse zero values cannot replace an existing positive observation. CSV fallback observations are also persisted. Reports aggregate the merged history, not only the latest 30-day response.

Rebuild saved history without live API calls or in-place writes:

```sh
python3 -m scripts.backfill_growth_history growth-history repaired-growth-history
```

The output contains normalized data, repaired snapshot copies, `backfill-audit.json`, and `backfill-summary.md`.

## Quality gate

Every snapshot includes `collection_quality` with counts, missing rate, typed issues, and an overall `ok`, `degraded`, or `error` state. The CLI can fail after writing diagnostics:

```sh
python3 -m growth_agent.main --quality-gate error
python3 -m growth_agent.main --quality-gate degraded
```

`error` catches authentication/fetch failures, a missing previous history snapshot, and unexplained historical gaps. `degraded` additionally fails on provider lag and GitHub traffic permission warnings. The production workflow must opt into the desired threshold only after review; the workflow file is intentionally unchanged.
