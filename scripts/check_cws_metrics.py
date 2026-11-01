#!/usr/bin/env python3
"""Verify WIF authentication by reading Chrome Web Store metrics."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ITEMS = {
    "PhraseCrate": "gngjinfejkkiflogppaadaandlenomcd",
    "Tab Parcel": "pohjmphoidcblbneaeabbpjhcjjlbhke",
}
METRICS = (
    "installs",
    "uninstalls",
    "users",
    "users-7d",
    "impressions",
    "page-views",
)


def query_url(publisher_id: str, item_id: str, first_date: date, last_date: date) -> str:
    params = {
        "metrics": METRICS,
        "timeSpec.firstDate.year": first_date.year,
        "timeSpec.firstDate.month": first_date.month,
        "timeSpec.firstDate.day": first_date.day,
        "timeSpec.lastDate.year": last_date.year,
        "timeSpec.lastDate.month": last_date.month,
        "timeSpec.lastDate.day": last_date.day,
        "pageSize": 1000,
    }
    resource = f"publishers/{publisher_id}/items/{item_id}"
    return f"https://chromewebstore.googleapis.com/v2/{resource}:queryMetrics?{urlencode(params, doseq=True)}"


def query_metrics(url: str, access_token: str) -> dict:
    request = Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def safe_error(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
        api_error = payload.get("error", {})
        return f"HTTP {error.code}: {api_error.get('status', 'UNKNOWN')} - {api_error.get('message', 'request failed')}"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"HTTP {error.code}: request failed"


def main() -> int:
    access_token = os.environ.get("CWS_ACCESS_TOKEN")
    publisher_id = os.environ.get("CWS_PUBLISHER_ID")
    if not access_token or not publisher_id:
        print("CWS_ACCESS_TOKEN and CWS_PUBLISHER_ID are required", file=sys.stderr)
        return 1

    last_date = date.today() - timedelta(days=1)
    first_date = last_date - timedelta(days=29)
    failures = []
    summary = [
        "## Chrome Web Store authentication test",
        "",
        f"Query period: `{first_date.isoformat()}` to `{last_date.isoformat()}`",
        "",
        "| Product | Result | Rows | Returned metrics |",
        "|---|---|---:|---|",
    ]

    for name, item_id in ITEMS.items():
        try:
            payload = query_metrics(query_url(publisher_id, item_id, first_date, last_date), access_token)
            rows = payload.get("metricRows")
            if not isinstance(rows, list) or not rows:
                failures.append(f"{name}: API returned no metric rows")
                summary.append(f"| {name} | No data | 0 | — |")
                continue
            returned_metrics = sorted(
                {
                    metric.get("metric", "")
                    for row in rows
                    for metric in row.get("metricValues", [])
                    if metric.get("metric")
                }
            )
            summary.append(f"| {name} | Success | {len(rows)} | {', '.join(returned_metrics) or '—'} |")
            print(f"{name}: queryMetrics succeeded with {len(rows)} rows")
        except HTTPError as error:
            message = safe_error(error)
            failures.append(f"{name}: {message}")
            summary.append(f"| {name} | Failed | — | `{message}` |")
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            message = f"{type(error).__name__}: request failed"
            failures.append(f"{name}: {message}")
            summary.append(f"| {name} | Failed | — | `{message}` |")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(summary) + "\n")

    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

