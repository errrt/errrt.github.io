import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import json
import os

from growth_agent.ai import analyze, log_line
from growth_agent.report import build_actions, render
from growth_agent.collectors import _public_store_metrics, _utc_range, collect_chrome_web_store, collect_cloudflare
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

    def test_actions_are_limited_to_three(self):
        snapshot = self.snapshot()
        snapshot["sources"]["x"] = {"status": "missing", "error": "token missing", "metrics": None}
        self.assertLessEqual(len(build_actions(snapshot, [])), 3)

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

    def test_report_makes_ai_fallback_explicit(self):
        snapshot = self.snapshot()
        snapshot["analysis"] = {
            "status": "error",
            "error": "OpenAI response was not completed: status=incomplete, reason=max_output_tokens",
            "result": None,
            "fallback": "rule_based",
            "diagnostics": {"response_status": "incomplete", "incomplete_reason": "max_output_tokens"},
        }
        snapshot["actions"] = build_actions(snapshot, [])
        report = render(snapshot, [])
        self.assertIn("## AI分析状態", report)
        self.assertIn("ルールベース分析へフォールバック", report)
        self.assertIn("reason=max_output_tokens", report)

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

    @patch("growth_agent.collectors._collect_public_store_item")
    def test_public_store_current_value_is_not_backdated(self, collect_public):
        config = {"products": [{"slug": "phrasecrate", "item_id": "item"}]}
        with tempfile.TemporaryDirectory() as directory:
            result = collect_chrome_web_store(config, date(2026, 10, 1), Path(directory), "Asia/Tokyo")
        self.assertEqual(result["phrasecrate"]["status"], "missing")
        self.assertIn("cannot be used as historical data", result["phrasecrate"]["error"])
        collect_public.assert_not_called()


class AIAnalysisTests(unittest.TestCase):
    def _completed_payload(self, text):
        return {
            "id": "resp_test",
            "model": "gpt-5-mini-2025-08-07",
            "status": "completed",
            "incomplete_details": None,
            "output": [{
                "type": "message",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }],
            "usage": {
                "input_tokens": 500,
                "output_tokens": 300,
                "output_tokens_details": {"reasoning_tokens": 100},
            },
        }

    @patch("growth_agent.ai.request_json")
    def test_structured_output_is_parsed_after_completed_status(self, request_json):
        result_json = {
            "summary": "要約",
            "observations": ["観測"],
            "hypotheses": ["仮説"],
            "opportunities": ["機会"],
        }
        request_json.return_value = self._completed_payload(
            json.dumps(result_json, ensure_ascii=False)
        )
        environment = {
            "OPENAI_API_KEY": "secret-test-key",
            "OPENAI_MODEL": "gpt-5-mini",
            "OPENAI_MAX_OUTPUT_TOKENS": "4000",
            "OPENAI_REASONING_EFFORT": "minimal",
        }
        with patch.dict(os.environ, environment):
            analysis = analyze({"sources": {}}, [])

        self.assertEqual(analysis["status"], "ok")
        self.assertEqual(analysis["result"], result_json)
        self.assertIsNone(analysis["fallback"])
        body = request_json.call_args.kwargs["body"]
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["max_output_tokens"], 4000)
        self.assertEqual(body["reasoning"], {"effort": "minimal"})
        self.assertNotIn("secret-test-key", log_line(analysis))

    @patch("growth_agent.ai.request_json")
    def test_incomplete_response_is_detected_before_json_parsing(self, request_json):
        request_json.return_value = {
            "id": "resp_incomplete",
            "model": "gpt-5-mini-2025-08-07",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{
                "type": "message",
                "status": "incomplete",
                "content": [{"type": "output_text", "text": '{"summary":"途中'}],
            }],
            "usage": {
                "input_tokens": 500,
                "output_tokens": 1200,
                "output_tokens_details": {"reasoning_tokens": 900},
            },
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze({"sources": {}}, [])

        self.assertEqual(analysis["status"], "error")
        self.assertEqual(analysis["fallback"], "rule_based")
        self.assertIn("status=incomplete", analysis["error"])
        self.assertIn("reason=max_output_tokens", analysis["error"])
        self.assertNotIn("途中", analysis["error"])

    @patch("growth_agent.ai.request_json")
    def test_json_failure_logs_metadata_without_response_content(self, request_json):
        request_json.return_value = self._completed_payload('{"summary":"private payload')
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze({"sources": {}}, [])

        self.assertEqual(analysis["status"], "error")
        self.assertIn("JSON decode failed", analysis["error"])
        self.assertIn("output_chars=", analysis["error"])
        self.assertNotIn("private payload", analysis["error"])


if __name__ == "__main__":
    unittest.main()
