import argparse
import json
from datetime import date
from pathlib import Path

from growth_agent.collectors import CWS_METRICS, _cws_metrics, _merge_cws_daily, _normalize_cws_pages
from growth_agent.quality import evaluate_quality


def _counts(daily):
    counts = {state: 0 for state in ("observed", "pending", "missing", "failed", "unavailable")}
    for values in daily.values():
        for metric in CWS_METRICS:
            state = values.get("metric_states", {}).get(metric.replace("-", "_"), "missing")
            counts[state if state in counts else "missing"] += 1
    return counts


def _changes(before, after):
    output = []
    for day in sorted(set(before) | set(after)):
        for api_metric in CWS_METRICS:
            metric = api_metric.replace("-", "_")
            old = before.get(day, {})
            new = after.get(day, {})
            old_pair = (old.get(metric), old.get("metric_states", {}).get(metric, "missing"))
            new_pair = (new.get(metric), new.get("metric_states", {}).get(metric, "missing"))
            if old_pair != new_pair:
                output.append({
                    "date": day, "metric": metric,
                    "before": {"value": old_pair[0], "state": old_pair[1]},
                    "after": {"value": new_pair[0], "state": new_pair[1]},
                    "provenance": new.get("metric_provenance", {}).get(metric),
                })
    return output


def main():
    parser = argparse.ArgumentParser(description="Rebuild normalized CWS history from saved raw API responses")
    parser.add_argument("history_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    normalized_dir = args.history_dir / "chrome-web-store" / "normalized"
    raw_root = args.history_dir / "chrome-web-store" / "raw"
    output_normalized = args.output_dir / "normalized"
    output_normalized.mkdir(parents=True, exist_ok=True)
    audit = {"products": {}, "snapshots": {"cloudflare_confirmed_zero": [], "rewritten": []}}
    rebuilt_products = {}

    for product_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        slug = product_dir.name
        source_path = normalized_dir / f"{slug}.json"
        source = json.loads(source_path.read_text(encoding="utf-8")) if source_path.exists() else {"daily": {}}
        before = source.get("daily", {})
        rebuilt = before
        last_fetched_at = source.get("updated_at")
        for raw_path in sorted(product_dir.glob("*.json")):
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            query = raw["query"]
            normalized = _normalize_cws_pages(
                raw.get("base", []), raw.get("dimensions", {}),
                date.fromisoformat(query["first_date"]), date.fromisoformat(query["last_date"]),
            )
            rebuilt = _merge_cws_daily(rebuilt, normalized)
            last_fetched_at = raw.get("fetched_at") or last_fetched_at
        observed_dates = sorted(
            day for day, values in rebuilt.items()
            if any(state == "observed" for state in values.get("metric_states", {}).values())
        )
        if observed_dates:
            first_observed = observed_dates[0]
            for day, values in rebuilt.items():
                if day >= first_observed:
                    continue
                for metric, state in values.get("metric_states", {}).items():
                    if state == "missing":
                        values["metric_states"][metric] = "unavailable"
                        values.setdefault("metric_provenance", {})[metric] = "api_no_date_row_before_first_observation"
        changes = _changes(before, rebuilt)
        payload = {"product": slug, "updated_at": last_fetched_at, "daily": rebuilt}
        (output_normalized / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        audit["products"][slug] = {
            "before": _counts(before), "after": _counts(rebuilt),
            "changed_cells": len(changes), "changes": changes,
        }
        rebuilt_products[slug] = {"daily": rebuilt, "updated_at": last_fetched_at}

    snapshots_dir = args.output_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    for snapshot_path in sorted(args.history_dir.glob("*.json")):
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        report_date = date.fromisoformat(snapshot["date"])
        cloudflare = snapshot.get("sources", {}).get("cloudflare", {})
        if (
            cloudflare.get("status") == "missing"
            and str(cloudflare.get("error", "")).startswith("Cloudflare returned no rows")
        ):
            cloudflare.update({
                "status": "ok", "error": None, "reason_code": "confirmed_zero",
                "metrics": {
                    "page_views": 0, "raw_page_views": 0, "visits": 0,
                    "unique_users": None, "referrers": [], "outbound_clicks": {},
                    "metric_states": {
                        "page_views": "observed", "raw_page_views": "observed",
                        "visits": "observed", "unique_users": "unavailable",
                    },
                },
            })
            audit["snapshots"]["cloudflare_confirmed_zero"].append(snapshot["date"])
        stores = snapshot.get("sources", {}).get("chrome_web_store", {})
        for slug, rebuilt in rebuilt_products.items():
            if slug not in stores:
                continue
            stores[slug] = {
                "status": "ok",
                "error": None,
                "metrics": _cws_metrics(
                    rebuilt["daily"], report_date, "chrome_web_store_api_v2_backfill",
                    rebuilt["updated_at"],
                    "Rebuilt from saved raw API responses; no live API request was made.",
                ),
            }
        snapshot["collection_quality"] = evaluate_quality(snapshot)
        (snapshots_dir / snapshot_path.name).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        audit["snapshots"]["rewritten"].append(snapshot["date"])

    before = {state: 0 for state in ("observed", "pending", "missing", "failed", "unavailable")}
    after = before.copy()
    for product in audit["products"].values():
        for state in before:
            before[state] += product["before"].get(state, 0)
            after[state] += product["after"].get(state, 0)
    snapshot_count = len(audit["snapshots"]["rewritten"])
    repaired_cloudflare = len(audit["snapshots"]["cloudflare_confirmed_zero"])
    before["observed"] += (snapshot_count - repaired_cloudflare) * 3
    before["missing"] += repaired_cloudflare * 3
    after["observed"] += snapshot_count * 3
    total = sum(before.values())
    audit["summary"] = {
        "cells": total,
        "before": before,
        "after": after,
        "actionable_missing_rate_before": (before["missing"] + before["failed"]) / total if total else 0,
        "actionable_missing_rate_after": (after["missing"] + after["failed"]) / total if total else 0,
        "incomplete_rate_before": (before["missing"] + before["failed"] + before["pending"] + before["unavailable"]) / total if total else 0,
        "incomplete_rate_after": (after["missing"] + after["failed"] + after["pending"] + after["unavailable"]) / total if total else 0,
    }

    (args.output_dir / "backfill-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = audit["summary"]
    (args.output_dir / "backfill-summary.md").write_text(
        "# Growth history backfill summary\n\n"
        f"- Audited cells: {summary['cells']}\n"
        f"- Actionable missing rate: {summary['actionable_missing_rate_before']:.1%} → "
        f"{summary['actionable_missing_rate_after']:.1%}\n"
        f"- All incomplete states (missing/failed/pending/unavailable): "
        f"{summary['incomplete_rate_before']:.1%} → {summary['incomplete_rate_after']:.1%}\n"
        f"- Before: `{json.dumps(summary['before'], ensure_ascii=False)}`\n"
        f"- After: `{json.dumps(summary['after'], ensure_ascii=False)}`\n"
        f"- Cloudflare empty aggregate days confirmed as zero: "
        f"{', '.join(audit['snapshots']['cloudflare_confirmed_zero']) or 'none'}\n"
        "- Provider-unavailable cells are retained as unavailable; they are never converted to zero.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
