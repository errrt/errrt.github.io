import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import os

from growth_agent.report import build_actions, render
from growth_agent.collectors import _public_store_metrics, _utc_range, collect_cloudflare
from datetime import date


class ReportTests(unittest.TestCase):
    def snapshot(self):
        return {
            "date": "2026-10-22",
            "sources": {
                "cloudflare": {"status": "missing", "error": "token missing", "metrics": None},
                "chrome_web_store": {"phrasecrate": {"status": "missing", "error": "CSV missing", "metrics": None}},
                "x": {"status": "ok", "error": None, "metrics": {"posts": 0, "post_metrics": []}},
                "github": {"status": "ok", "error": None, "metrics": {"errrt/errrt.github.io": {"status": "ok", "error": None, "metrics": {"stars": 3}}}},
            },
        }

    def test_missing_is_not_rendered_as_zero(self):
        snapshot = self.snapshot()
        snapshot["actions"] = build_actions(snapshot, [])
        report = render(snapshot, [])
        self.assertIn("| errrt LP | — | — |", report)
        self.assertIn("| phrasecrate | — | — | — | — |", report)
        self.assertIn("## 流入経路の分析", report)
        self.assertIn("## ボトルネック", report)
        self.assertIn("## 前日の施策と結果", report)

    def test_duplicate_actions_are_suppressed(self):
        snapshot = self.snapshot()
        first = build_actions(snapshot, [])
        history = [{"actions": first}]
        self.assertEqual(build_actions(snapshot, history), [])

    def test_report_shows_absolute_and_percent_change(self):
        snapshot = self.snapshot()
        snapshot["sources"]["cloudflare"] = {
            "status": "ok", "error": None,
            "metrics": {"page_views": 12, "visits": 6, "referrers": [], "outbound_clicks": {}},
        }
        snapshot["actions"] = []
        previous = self.snapshot()
        previous["sources"]["cloudflare"] = {
            "status": "ok", "error": None,
            "metrics": {"page_views": 10, "visits": 5},
        }
        report = render(snapshot, [previous])
        self.assertIn("平均 10 比 +2 / +20.0%", report)

    def test_jst_day_is_converted_to_utc(self):
        start, end = _utc_range(date(2026, 10, 22), "Asia/Tokyo")
        self.assertEqual(start, "2026-10-21T15:00:00Z")
        self.assertEqual(end, "2026-10-22T15:00:00Z")

    @patch("growth_agent.collectors.request_json")
    def test_cloudflare_separates_outbound_clicks_from_lp_views(self, request_json):
        request_json.return_value = {"data": {"viewer": {"accounts": [{
            "totals": [{"count": 10, "sum": {"visits": 6}}],
            "referrers": [],
            "paths": [
                {"count": 8, "dimensions": {"requestPath": "/"}},
                {"count": 2, "dimensions": {"requestPath": "/go/phraseCrate/"}},
            ],
        }]}}}
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": "account"}):
            result = collect_cloudflare({"site_tag": "site"}, date(2026, 10, 22), "Asia/Tokyo")
        self.assertEqual(result["metrics"]["page_views"], 8)
        self.assertEqual(result["metrics"]["outbound_clicks"], {"phraseCrate": 2})

    def test_public_store_listing_is_explicitly_partial(self):
        page = (
            '<a href="/category/extensions/productivity/tools">Tools</a>4 users</div>'
            '<h2>0 out of 5</h2><span class="PmmSTd">No ratings</span>'
        )
        metrics = _public_store_metrics(page)
        self.assertEqual(metrics["users"], 4)
        self.assertEqual(metrics["reviews"], 0)
        self.assertIsNone(metrics["installs"])
        self.assertEqual(metrics["data_source"], "public_listing")

    def test_public_store_parses_rounded_counts(self):
        page = (
            '<a href="/category/extensions/productivity/tools">Tools</a>1.5K+ users</div>'
            '<h2>4.8 out of 5</h2><span class="PmmSTd">1,234 ratings</span>'
        )
        metrics = _public_store_metrics(page)
        self.assertEqual(metrics["users"], 1500)
        self.assertEqual(metrics["rating"], 4.8)
        self.assertEqual(metrics["reviews"], 1234)


if __name__ == "__main__":
    unittest.main()
