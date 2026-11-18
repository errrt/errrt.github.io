from datetime import date, timedelta


REQUIRED_CWS_METRICS = ("installs", "uninstalls", "impressions", "page_views", "users", "users_7d")


def evaluate_quality(snapshot, history=None):
    issues = []
    counts = {state: 0 for state in ("observed", "pending", "missing", "failed", "unavailable")}

    if history is not None:
        report_date = date.fromisoformat(snapshot["date"])
        expected_previous = (report_date - timedelta(days=1)).isoformat()
        history_dates = {item.get("date") for item in history}
        if history and expected_previous not in history_dates:
            issues.append({
                "severity": "error",
                "source": "history",
                "reason_code": "history_gap",
                "message": f"Expected previous snapshot {expected_previous} was not restored",
            })
        elif not history:
            issues.append({
                "severity": "error",
                "source": "history",
                "reason_code": "history_restore_empty",
                "message": "No previous growth history was restored",
            })

    cloudflare = snapshot["sources"]["cloudflare"]
    if cloudflare.get("status") != "ok":
        issues.append({
            "severity": "error",
            "source": "cloudflare",
            "reason_code": cloudflare.get("reason_code", "fetch_error"),
            "message": cloudflare.get("error") or "Cloudflare collection failed",
        })
        counts["failed" if cloudflare.get("status") == "error" else "missing"] += 3
    else:
        counts["observed"] += 3

    for slug, source in snapshot["sources"]["chrome_web_store"].items():
        if source.get("status") not in ("ok", "partial") or not source.get("metrics"):
            issues.append({
                "severity": "error",
                "source": f"chrome_web_store/{slug}",
                "reason_code": source.get("reason_code", "fetch_error"),
                "message": source.get("error") or "CWS collection failed",
            })
            counts["failed" if source.get("status") == "error" else "missing"] += len(REQUIRED_CWS_METRICS) * 30
            continue
        daily = source["metrics"].get("daily", {})
        cws_report_date = date.fromisoformat(snapshot["date"])
        selected = [(cws_report_date - timedelta(days=offset)).isoformat() for offset in range(30)]
        coverage_by_metric = {}
        for day in selected:
            for metric in REQUIRED_CWS_METRICS:
                state = daily.get(day, {}).get("metric_states", {}).get(metric, "missing")
                counts[state if state in counts else "missing"] += 1
                metric_counts = coverage_by_metric.setdefault(
                    metric, {key: 0 for key in ("observed", "pending", "missing", "failed", "unavailable")}
                )
                metric_counts[state if state in metric_counts else "missing"] += 1
        for metric, coverage in coverage_by_metric.items():
            if coverage["missing"] or coverage["failed"]:
                issues.append({
                    "severity": "error",
                    "source": f"chrome_web_store/{slug}/{metric}",
                    "reason_code": "historical_gap",
                    "message": (
                        f"30d coverage has missing={coverage['missing']} "
                        f"failed={coverage['failed']} days"
                    ),
                })
            elif coverage["pending"]:
                issues.append({
                    "severity": "warning",
                    "source": f"chrome_web_store/{slug}/{metric}",
                    "reason_code": "provider_pending",
                    "message": f"30d coverage has pending={coverage['pending']} day(s)",
                })
            if coverage["unavailable"]:
                issues.append({
                    "severity": "limitation",
                    "source": f"chrome_web_store/{slug}/{metric}",
                    "reason_code": "provider_unavailable",
                    "message": f"30d coverage has unavailable={coverage['unavailable']} day(s)",
                })

    github = snapshot["sources"]["github"]
    for repo, source in (github.get("metrics") or {}).items():
        if source.get("status") == "partial":
            issues.append({
                "severity": "warning",
                "source": f"github/{repo}/traffic",
                "reason_code": "authentication_error",
                "message": source.get("error") or "GitHub traffic is unavailable",
            })

    x_source = snapshot["sources"]["x"]
    if x_source.get("status") != "ok":
        issues.append({
            "severity": "limitation",
            "source": "x",
            "reason_code": "paid_source_not_configured",
            "message": x_source.get("error") or "X collection is not configured",
        })
        counts["unavailable"] += 1

    severities = {issue["severity"] for issue in issues}
    status = "error" if "error" in severities else ("degraded" if "warning" in severities else "ok")
    known_total = sum(counts[state] for state in ("observed", "pending", "missing", "failed"))
    missing_rate = (counts["missing"] + counts["failed"]) / known_total if known_total else 0
    return {
        "status": status,
        "counts": counts,
        "missing_rate": missing_rate,
        "issues": issues,
    }
