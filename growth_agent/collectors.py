import csv
import html
import json
import os
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from .http import request_json, request_text


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
        return {"status": "ok", "error": None, "metrics": {
            "page_views": page_views, "raw_page_views": raw_page_views, "visits": visits,
            "unique_users": None, "referrers": referrers, "outbound_clicks": outbound_clicks,
        }}
    except Exception as error:
        return failed(error)


def _number(value):
    normalized = value.replace(",", "").strip().upper()
    multiplier = 1
    if normalized.endswith("K"):
        multiplier, normalized = 1_000, normalized[:-1]
    elif normalized.endswith("M"):
        multiplier, normalized = 1_000_000, normalized[:-1]
    return float(normalized) * multiplier


def _public_store_metrics(page):
    text = html.unescape(page)
    users_match = re.search(r"([\d,.]+\s*[KM]?)\+? users</div>", text, re.IGNORECASE)
    rating_match = re.search(r"([\d.]+) out of 5", text, re.IGNORECASE)
    reviews_match = re.search(r'class="PmmSTd">\s*([\d,]+) ratings?\s*</span>', text, re.IGNORECASE)
    no_ratings = re.search(r'class="PmmSTd">\s*No ratings\s*</span>', text, re.IGNORECASE)
    if not users_match:
        raise RuntimeError("Public listing did not contain a user count")
    return {
        "installs": None,
        "uninstalls": None,
        "users": _number(users_match.group(1).replace(" ", "")),
        "impressions": None,
        "rating": float(rating_match.group(1)) if rating_match else None,
        "reviews": float(reviews_match.group(1).replace(",", "")) if reviews_match else (0.0 if no_ratings else None),
        "acquisition_source": None,
        "data_source": "public_listing",
        "limitations": "Public user counts may be rounded; installs, uninstalls, impressions, and acquisition sources are unavailable.",
    }


def _collect_public_store_item(product):
    item_id = product["item_id"]
    slug = product["slug"]
    url = product.get("url") or f"https://chromewebstore.google.com/detail/{slug}/{item_id}"
    page = request_text(url)
    return {"status": "partial", "error": None, "metrics": _public_store_metrics(page)}


def collect_chrome_web_store(config, report_date, imports_dir):
    results = {}
    for product in config.get("products", []):
        slug = product["slug"]
        path = imports_dir / f"{slug}.csv"
        if not path.exists():
            try:
                results[slug] = _collect_public_store_item(product)
            except Exception as error:
                results[slug] = missing(
                    f"Official analytics CSV is absent and public listing fallback failed: {error}"
                )
            continue
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            matching = [row for row in rows if row.get("date", row.get("Date")) == report_date.isoformat()]
            if not matching:
                try:
                    results[slug] = _collect_public_store_item(product)
                    results[slug]["metrics"]["limitations"] = (
                        f"Official CSV has no row for {report_date.isoformat()}; "
                        + results[slug]["metrics"]["limitations"]
                    )
                except Exception as error:
                    results[slug] = missing(f"No CSV row for {report_date.isoformat()} and public fallback failed: {error}")
                continue
            row = matching[-1]
            metrics = {}
            for key in ("installs", "uninstalls", "users", "impressions", "rating", "reviews"):
                raw = row.get(key, row.get(key.title()))
                metrics[key] = float(raw) if raw not in (None, "") else None
            metrics["acquisition_source"] = row.get("acquisition_source", row.get("Acquisition Source")) or None
            metrics["data_source"] = "official_csv"
            metrics["limitations"] = None
            results[slug] = {"status": "ok", "error": None, "metrics": metrics}
        except Exception as error:
            results[slug] = failed(error)
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
