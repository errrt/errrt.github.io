import csv
import json
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from .http import request_json


def missing(reason):
    return {"status": "missing", "error": reason, "metrics": None}


def failed(error):
    return {"status": "error", "error": str(error), "metrics": None}


def _utc_range(report_date, timezone_name):
    local_start = datetime.combine(report_date, time.min, ZoneInfo(timezone_name))
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    return (
        utc_start.isoformat().replace("+00:00", "Z"),
        utc_end.isoformat().replace("+00:00", "Z"),
    )


def collect_cloudflare(config, report_date, timezone_name):
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID") or config.get("account_id")
    site_tag = config.get("site_tag")
    if not token or not account_id or not site_tag:
        return missing("CLOUDFLARE_API_TOKEN, account_id, and site_tag are required")

    start, end = _utc_range(report_date, timezone_name)
    query = """
    query Daily($accountTag: String!, $siteTag: String!, $start: Time!, $end: Time!) {
      viewer { accounts(filter: {accountTag: $accountTag}) {
        totals: rumPageloadEventsAdaptiveGroups(limit: 1, filter: {siteTag: $siteTag, datetime_geq: $start, datetime_lt: $end}) {
          count sum { visits }
        }
        referrers: rumPageloadEventsAdaptiveGroups(limit: 20, orderBy: [count_DESC], filter: {siteTag: $siteTag, datetime_geq: $start, datetime_lt: $end}) {
          count dimensions { refererHost }
        }
        paths: rumPageloadEventsAdaptiveGroups(limit: 100, orderBy: [count_DESC], filter: {siteTag: $siteTag, datetime_geq: $start, datetime_lt: $end}) {
          count dimensions { requestPath }
        }
      }}
    }
    """
    try:
        payload = request_json(
            "https://api.cloudflare.com/client/v4/graphql",
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            body={"query": query, "variables": {"accountTag": account_id, "siteTag": site_tag, "start": start, "end": end}},
        )
        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
        accounts = payload["data"]["viewer"]["accounts"]
        if not accounts:
            raise RuntimeError("No Cloudflare account data returned")
        totals = accounts[0]["totals"]
        if not totals:
            return {
                "status": "missing",
                "error": (
                    "Cloudflare returned no rows for "
                    f"{start} to {end}; the result is unknown, not a confirmed zero"
                ),
                "metrics": None,
                "query_window": {"start": start, "end": end},
            }
        raw_page_views = sum(row.get("count", 0) for row in totals)
        visits = sum(row.get("sum", {}).get("visits", 0) for row in totals)
        referrers = [
            {"host": row["dimensions"].get("refererHost") or "direct", "page_views": row.get("count", 0)}
            for row in accounts[0]["referrers"]
        ]
        outbound_clicks = {}
        for row in accounts[0]["paths"]:
            path_parts = row["dimensions"].get("requestPath", "").strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] == "go":
                outbound_clicks[path_parts[1]] = outbound_clicks.get(path_parts[1], 0) + row.get("count", 0)
        page_views = max(raw_page_views - sum(outbound_clicks.values()), 0)
        return {"status": "ok", "error": None, "query_window": {"start": start, "end": end}, "metrics": {
            "page_views": page_views, "raw_page_views": raw_page_views, "visits": visits,
            "unique_users": None, "referrers": referrers, "outbound_clicks": outbound_clicks,
        }}
    except Exception as error:
        return failed(error)


CWS_METRICS = ("installs", "uninstalls", "impressions", "page-views", "users", "users-7d")


def _cws_url(publisher_id, item_id, first_date, last_date, metrics, dimension=None, page_token=None):
    params = {
        "metrics": metrics,
        "timeSpec.firstDate.year": first_date.year,
        "timeSpec.firstDate.month": first_date.month,
        "timeSpec.firstDate.day": first_date.day,
        "timeSpec.lastDate.year": last_date.year,
        "timeSpec.lastDate.month": last_date.month,
        "timeSpec.lastDate.day": last_date.day,
        "pageSize": 1000,
    }
    if dimension:
        params["dimensions"] = dimension
    if page_token:
        params["pageToken"] = page_token
    resource = f"publishers/{publisher_id}/items/{item_id}"
    return f"https://chromewebstore.googleapis.com/v2/{resource}:queryMetrics?{urlencode(params, doseq=True)}"


def _cws_query_pages(publisher_id, item_id, first_date, last_date, metrics, token, dimension=None):
    pages = []
    page_token = None
    while True:
        payload = request_json(
            _cws_url(publisher_id, item_id, first_date, last_date, metrics, dimension, page_token),
            headers={"Authorization": f"Bearer {token}"},
        )
        if not isinstance(payload.get("metricRows", []), list):
            raise RuntimeError("Chrome Web Store API response has no metricRows array")
        pages.append(payload)
        page_token = payload.get("nextPageToken")
        if not page_token:
            return pages


def _cws_date(row):
    value = row.get("date") or {}
    return f"{int(value['year']):04d}-{int(value['month']):02d}-{int(value['day']):02d}"


def _metric_value(value):
    raw = value.get("value")
    return int(raw) if raw not in (None, "") else None


def _empty_day(state="missing"):
    return {
        "installs": None,
        "uninstalls": None,
        "impressions": None,
        "page_views": None,
        "users": None,
        "users_7d": None,
        "metric_states": {metric.replace("-", "_"): state for metric in CWS_METRICS},
        "install_sources": None,
        "utm_sources": None,
    }


def _normalize_cws_pages(base_pages, dimension_pages, first_date, last_date):
    dates = {}
    current = first_date
    while current <= last_date:
        dates[current.isoformat()] = _empty_day()
        current += timedelta(days=1)

    returned_dates = []
    for payload in base_pages:
        for row in payload.get("metricRows", []):
            day = _cws_date(row)
            returned_dates.append(day)
            target = dates.setdefault(day, _empty_day())
            for metric in row.get("metricValues", []):
                key = metric.get("metric", "").replace("-", "_")
                if key in target["metric_states"]:
                    target[key] = _metric_value(metric)
                    target["metric_states"][key] = "observed"

    # The API does not expose a finalization flag. Dates after its latest returned
    # date are marked pending, rather than being converted to zeros.
    latest_returned = max(returned_dates, default=None)
    if latest_returned:
        for day, values in dates.items():
            if day > latest_returned:
                values["metric_states"] = {key: "pending" for key in values["metric_states"]}

    for dimension, pages in dimension_pages.items():
        field = "install_sources" if dimension == "install-source" else "utm_sources"
        for payload in pages:
            for row in payload.get("metricRows", []):
                day = _cws_date(row)
                values = dates.setdefault(day, _empty_day())
                values[field] = values[field] or {}
                label = (row.get("dimensionValues") or ["unknown"])[0]
                values[field][label] = {
                    metric.get("metric", "").replace("-", "_"): _metric_value(metric)
                    for metric in row.get("metricValues", [])
                }
    return dates


def _period(daily, last_date, days):
    selected = [(last_date - timedelta(days=offset)).isoformat() for offset in range(days)]
    output = {}
    for metric in ("installs", "uninstalls", "impressions", "page_views"):
        observed = [day for day in selected if daily.get(day, {}).get("metric_states", {}).get(metric) == "observed"]
        values = [daily[day][metric] for day in observed if daily[day].get(metric) is not None]
        output[metric] = {
            "value": sum(values) if values else None,
            "state": "complete" if len(observed) == days else ("partial" if observed else "missing"),
            "observed_days": len(observed),
            "expected_days": days,
        }
    return output


def _latest_active(daily, metric, last_date):
    candidates = [
        (day, values.get(metric))
        for day, values in daily.items()
        if day <= last_date.isoformat()
        and values.get("metric_states", {}).get(metric) == "observed"
        and values.get(metric) is not None
    ]
    if not candidates:
        return {"value": None, "date": None, "state": "missing", "trend_7d": []}
    day, value = max(candidates)
    trend = [
        {"date": date_key, "value": daily.get(date_key, {}).get(metric)}
        for date_key in (
            (last_date - timedelta(days=offset)).isoformat()
            for offset in reversed(range(7))
        )
        if daily.get(date_key, {}).get("metric_states", {}).get(metric) == "observed"
    ]
    return {"value": value, "date": day, "state": "observed", "trend_7d": trend}


def _conversion(period):
    installs = period["installs"]
    page_views = period["page_views"]
    if installs["state"] != "complete" or page_views["state"] != "complete" or not page_views["value"]:
        return None
    return installs["value"] / page_views["value"]


def _source_totals(daily, last_date, days, field):
    totals = {}
    for offset in range(days):
        values = daily.get((last_date - timedelta(days=offset)).isoformat(), {}).get(field) or {}
        for source, metrics in values.items():
            target = totals.setdefault(source, {})
            for metric, value in metrics.items():
                if value is not None:
                    target[metric] = target.get(metric, 0) + value
    return totals or None


def _cws_metrics(daily, report_date, data_source, fetched_at, limitations=None):
    periods = {label: _period(daily, report_date, days) for label, days in (("1d", 1), ("7d", 7), ("30d", 30))}
    day = daily.get(report_date.isoformat(), _empty_day())
    return {
        **{key: day.get(key) for key in ("installs", "uninstalls", "impressions", "page_views", "users", "users_7d")},
        "metric_states": day["metric_states"],
        "daily": daily,
        "periods": periods,
        "conversion_rate": {label: _conversion(period) for label, period in periods.items()},
        "active_users": {
            "users": _latest_active(daily, "users", report_date),
            "users_7d": _latest_active(daily, "users_7d", report_date),
        },
        "install_sources": day.get("install_sources"),
        "utm_sources": day.get("utm_sources"),
        "source_breakdown_30d": {
            "install_source": _source_totals(daily, report_date, 30, "install_sources"),
            "utm_source": _source_totals(daily, report_date, 30, "utm_sources"),
        },
        "data_source": data_source,
        "last_updated_at": fetched_at,
        "limitations": limitations,
    }


def _read_cws_csv(path, first_date, last_date):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    daily = {}
    for row in rows:
        day = row.get("date", row.get("Date"))
        if not day or not first_date.isoformat() <= day <= last_date.isoformat():
            continue
        values = _empty_day()
        for key in ("installs", "uninstalls", "impressions", "page_views", "users", "users_7d"):
            raw = row.get(key, row.get(key.replace("_", "-").title()))
            if raw not in (None, ""):
                values[key] = int(float(raw))
                values["metric_states"][key] = "observed"
        source = row.get("acquisition_source", row.get("Acquisition Source"))
        if source:
            values["install_sources"] = {source: {"installs": values["installs"]}}
        daily[day] = values
    current = first_date
    while current <= last_date:
        daily.setdefault(current.isoformat(), _empty_day())
        current += timedelta(days=1)
    return daily


def _save_cws_data(storage_dir, slug, report_date, raw, daily, fetched_at):
    raw_dir = storage_dir / "raw" / slug
    normalized_dir = storage_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{report_date.isoformat()}.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    normalized_path = normalized_dir / f"{slug}.json"
    existing = {}
    if normalized_path.exists():
        try:
            existing = json.loads(normalized_path.read_text(encoding="utf-8")).get("daily", {})
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.update(daily)
    normalized_path.write_text(
        json.dumps({"product": slug, "updated_at": fetched_at, "daily": existing}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def collect_chrome_web_store(config, report_date, imports_dir, storage_dir=None, timezone_name="Asia/Tokyo"):
    results = {}
    token = os.getenv("CWS_ACCESS_TOKEN")
    publisher_id = os.getenv("CWS_PUBLISHER_ID")
    first_date = report_date - timedelta(days=29)
    fetched_at = datetime.now(ZoneInfo(timezone_name)).isoformat()
    storage_dir = storage_dir or Path("growth-history/chrome-web-store")
    for product in config.get("products", []):
        slug = product["slug"]
        api_error = None
        if token and publisher_id:
            try:
                base_pages = _cws_query_pages(
                    publisher_id, product["item_id"], first_date, report_date, CWS_METRICS, token
                )
                dimension_pages = {}
                dimension_errors = []
                for dimension, metrics in (("install-source", ("installs",)), ("utm-source", ("installs", "page-views"))):
                    try:
                        dimension_pages[dimension] = _cws_query_pages(
                            publisher_id, product["item_id"], first_date, report_date, metrics, token, dimension
                        )
                    except Exception as error:
                        dimension_errors.append(f"{dimension}: {error}")
                daily = _normalize_cws_pages(base_pages, dimension_pages, first_date, report_date)
                raw = {
                    "product": slug,
                    "item_id": product["item_id"],
                    "fetched_at": fetched_at,
                    "query": {"first_date": first_date.isoformat(), "last_date": report_date.isoformat()},
                    "base": base_pages,
                    "dimensions": dimension_pages,
                    "dimension_errors": dimension_errors,
                }
                _save_cws_data(storage_dir, slug, report_date, raw, daily, fetched_at)
                limitations = (
                    "Dimension queries were unavailable: " + "; ".join(dimension_errors)
                    if dimension_errors else None
                )
                metrics = _cws_metrics(daily, report_date, "chrome_web_store_api_v2", fetched_at, limitations)
                results[slug] = {"status": "partial" if dimension_errors else "ok", "error": limitations, "metrics": metrics}
                continue
            except Exception as error:
                api_error = str(error)
        else:
            api_error = "CWS_ACCESS_TOKEN and CWS_PUBLISHER_ID are required for the official API"

        path = imports_dir / f"{slug}.csv"
        if not path.exists():
            results[slug] = missing(f"Official API unavailable ({api_error}); fallback CSV is absent")
            continue
        try:
            daily = _read_cws_csv(path, first_date, report_date)
            metrics = _cws_metrics(
                daily, report_date, "official_csv", fetched_at,
                f"Official API unavailable ({api_error}); using the CSV fallback.",
            )
            results[slug] = {"status": "partial", "error": metrics["limitations"], "metrics": metrics}
        except Exception as error:
            results[slug] = failed(f"Official API failed ({api_error}); CSV fallback failed: {error}")
    return results


def collect_x(config, report_date, timezone_name):
    token = os.getenv("X_BEARER_TOKEN")
    username = config.get("username")
    if not token or not username:
        return missing("X_BEARER_TOKEN and x.username are required; X API reads are paid")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        user = request_json(f"https://api.x.com/2/users/by/username/{quote(username)}", headers=headers)["data"]
        start, end = _utc_range(report_date, timezone_name)
        params = urlencode({
            "start_time": start,
            "end_time": end,
            "max_results": 100,
            "exclude": "retweets,replies",
            "tweet.fields": "created_at,public_metrics",
        })
        payload = request_json(f"https://api.x.com/2/users/{user['id']}/tweets?{params}", headers=headers)
        posts = payload.get("data", [])
        post_metrics = []
        for post in posts:
            metrics = post.get("public_metrics", {})
            engagements = sum(metrics.get(key, 0) for key in ("like_count", "retweet_count", "reply_count", "quote_count"))
            impressions = metrics.get("impression_count")
            post_metrics.append({
                "id": post["id"], "text": post.get("text", ""), "impressions": impressions,
                "likes": metrics.get("like_count"), "reposts": metrics.get("retweet_count"),
                "replies": metrics.get("reply_count"), "quotes": metrics.get("quote_count"),
                "engagement_rate": (engagements / impressions if impressions else None),
            })
        impressions = [post["impressions"] for post in post_metrics if isinstance(post["impressions"], (int, float))]
        total_impressions = sum(impressions) if impressions else None
        likes = sum(post["likes"] or 0 for post in post_metrics)
        reposts = sum(post["reposts"] or 0 for post in post_metrics)
        replies = sum(post["replies"] or 0 for post in post_metrics)
        quotes = sum(post["quotes"] or 0 for post in post_metrics)
        engagements = likes + reposts + replies + quotes
        return {"status": "ok", "error": None, "metrics": {
            "posts": len(posts), "impressions": total_impressions, "likes": likes,
            "reposts": reposts, "replies": replies, "quotes": quotes,
            "engagement_rate": engagements / total_impressions if total_impressions else None,
            "post_metrics": post_metrics,
        }}
    except Exception as error:
        return failed(error)


def _github_get(path, token):
    headers = {
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return request_json(
        f"https://api.github.com{path}",
        headers=headers,
    )


def collect_github(config, report_date, timezone_name):
    token = os.getenv("GROWTH_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    start, end = _utc_range(report_date, timezone_name)
    results = {}
    for repo in config.get("repositories", []):
        try:
            metadata = _github_get(f"/repos/{repo}", token)
            commits = _github_get(f"/repos/{repo}/commits?since={quote(start)}&until={quote(end)}&per_page=100", token)
            issues = _github_get(f"/repos/{repo}/issues?state=all&since={quote(start)}&per_page=100", token)
            in_window = lambda item: start <= item.get("created_at", "") < end
            issue_count = sum(1 for item in issues if "pull_request" not in item and in_window(item))
            pr_count = sum(1 for item in issues if "pull_request" in item and in_window(item))
            traffic_error = None
            day_views = {}
            day_clones = {}
            try:
                views = _github_get(f"/repos/{repo}/traffic/views?per=day", token)
                clones = _github_get(f"/repos/{repo}/traffic/clones?per=day", token)
                # GitHub traffic buckets are fixed at UTC midnight and cannot be rebucketed to JST.
                utc_day = start[:10]
                day_views = next((row for row in views.get("views", []) if row["timestamp"].startswith(utc_day)), {})
                day_clones = next((row for row in clones.get("clones", []) if row["timestamp"].startswith(utc_day)), {})
            except Exception as error:
                traffic_error = f"Traffic metrics unavailable: {error}"
            results[repo] = {"status": "partial" if traffic_error else "ok", "error": traffic_error, "metrics": {
                "commits": len(commits), "issues_created": issue_count, "prs_created": pr_count,
                "stars": metadata.get("stargazers_count"), "open_issues": metadata.get("open_issues_count"),
                "views": day_views.get("count"), "unique_visitors": day_views.get("uniques"),
                "clones": day_clones.get("count"), "unique_cloners": day_clones.get("uniques"),
            }}
        except Exception as error:
            results[repo] = failed(error)
    usable = any(v["status"] in ("ok", "partial") for v in results.values())
    return {"status": "ok" if usable else "error", "error": None, "metrics": results}
