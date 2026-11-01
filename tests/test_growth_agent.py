import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import json
import os

from growth_agent.ai import analyze, log_line
from growth_agent.report import build_actions, render
from growth_agent.collectors import _utc_range, collect_chrome_web_store, collect_cloudflare
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

    def test_report_shows_cws_periods_coverage_and_active_users(self):
        snapshot = self.snapshot()
        snapshot["sources"]["chrome_web_store"]["phrasecrate"] = {
            "status": "ok", "error": None,
            "metrics": {
                "installs": None, "page_views": None,
                "periods": {
                    "1d": {key: {"value": None, "state": "missing", "observed_days": 0, "expected_days": 1} for key in ("installs", "uninstalls", "impressions", "page_views")},
                    "7d": {key: {"value": 7, "state": "partial", "observed_days": 5, "expected_days": 7} for key in ("installs", "uninstalls", "impressions", "page_views")},
                    "30d": {key: {"value": 30, "state": "complete", "observed_days": 30, "expected_days": 30} for key in ("installs", "uninstalls", "impressions", "page_views")},
                },
                "conversion_rate": {"1d": None, "7d": None, "30d": 0.1},
                "active_users": {
                    "users": {"value": 4, "date": "2026-10-21", "trend_7d": [{"date": "2026-10-21", "value": 4}]},
                    "users_7d": {"value": 3, "date": "2026-10-21", "trend_7d": []},
                },
                "data_source": "chrome_web_store_api_v2",
                "last_updated_at": "2026-10-22T05:00:00+09:00",
            },
        }
        snapshot["actions"] = []
        report = render(snapshot, [])
        self.assertIn("### Chrome Web Store公式Metrics", report)
        self.assertIn("7 (5/7日)", report)
        self.assertIn("10.0%", report)
        self.assertIn("Daily active users: 4 (2026-10-21)", report)
        self.assertIn("10-21:4", report)

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

    @patch("growth_agent.collectors.request_json")
    def test_cloudflare_empty_response_is_missing_not_zero(self, request_json):
        request_json.return_value = {"data": {"viewer": {"accounts": [{
            "totals": [],
            "referrers": [],
            "paths": [],
        }]}}}
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": "account"}):
            result = collect_cloudflare({"site_tag": "site"}, date(2026, 10, 22), "Asia/Tokyo")
        self.assertEqual(result["status"], "missing")
        self.assertIsNone(result["metrics"])
        self.assertIn("unknown, not a confirmed zero", result["error"])
        self.assertEqual(result["query_window"]["start"], "2026-10-21T15:00:00Z")

    @patch("growth_agent.collectors.request_json")
    def test_cws_api_paginates_and_preserves_zero_missing_and_pending(self, request_json):
        config = {"products": [{"slug": "phrasecrate", "item_id": "item"}]}
        request_json.side_effect = [
            {"metricRows": [{
                "date": {"year": 2026, "month": 10, "day": 20},
                "metricValues": [
                    {"metric": "installs", "value": "0"},
                    {"metric": "users", "value": "4"},
                ],
            }], "nextPageToken": "next"},
            {"metricRows": [{
                "date": {"year": 2026, "month": 10, "day": 21},
                "metricValues": [{"metric": "installs", "value": "2"}],
            }]},
            {"metricRows": [{
                "date": {"year": 2026, "month": 10, "day": 21},
                "dimensionValues": ["organic"],
                "metricValues": [{"metric": "installs", "value": "2"}],
            }]},
            {"metricRows": []},
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"CWS_ACCESS_TOKEN": "token", "CWS_PUBLISHER_ID": "publisher"}):
                result = collect_chrome_web_store(
                    config, date(2026, 10, 22), Path(directory), Path(directory) / "history"
                )
            raw = json.loads((Path(directory) / "history/raw/phrasecrate/2026-10-22.json").read_text())
            normalized = json.loads((Path(directory) / "history/normalized/phrasecrate.json").read_text())
        metrics = result["phrasecrate"]["metrics"]
        self.assertEqual(metrics["daily"]["2026-10-20"]["installs"], 0)
        self.assertEqual(metrics["daily"]["2026-10-20"]["metric_states"]["installs"], "observed")
        self.assertIsNone(metrics["daily"]["2026-10-20"]["uninstalls"])
        self.assertEqual(metrics["daily"]["2026-10-20"]["metric_states"]["uninstalls"], "missing")
        self.assertEqual(metrics["daily"]["2026-10-22"]["metric_states"]["installs"], "pending")
        self.assertEqual(metrics["periods"]["30d"]["installs"]["value"], 2)
        self.assertEqual(metrics["periods"]["30d"]["installs"]["observed_days"], 2)
        self.assertEqual(metrics["source_breakdown_30d"]["install_source"]["organic"]["installs"], 2)
        self.assertEqual(len(raw["base"]), 2)
        self.assertIn("2026-10-21", normalized["daily"])
        self.assertIn("pageToken=next", request_json.call_args_list[1].args[0])
        self.assertNotIn("token", json.dumps(raw))

    @patch("growth_agent.collectors.request_json", side_effect=RuntimeError("API denied"))
    def test_cws_api_failure_uses_csv_without_scraping(self, _request_json):
        config = {"products": [{"slug": "phrasecrate", "item_id": "item"}]}
        with tempfile.TemporaryDirectory() as directory:
            imports = Path(directory) / "imports"
            imports.mkdir()
            (imports / "phrasecrate.csv").write_text(
                "date,installs,uninstalls,users,impressions,page_views,users_7d\n"
                "2026-10-22,1,,4,20,5,3\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CWS_ACCESS_TOKEN": "token", "CWS_PUBLISHER_ID": "publisher"}):
                result = collect_chrome_web_store(config, date(2026, 10, 22), imports, Path(directory) / "history")
        source = result["phrasecrate"]
        self.assertEqual(source["status"], "partial")
        self.assertEqual(source["metrics"]["data_source"], "official_csv")
        self.assertEqual(source["metrics"]["installs"], 1)
        self.assertIsNone(source["metrics"]["uninstalls"])
        self.assertIn("API denied", source["error"])

    def test_cws_missing_auth_is_not_zero(self):
        config = {"products": [{"slug": "phrasecrate", "item_id": "item"}]}
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {}, clear=True):
                result = collect_chrome_web_store(
                    config, date(2026, 10, 22), Path(directory), Path(directory) / "history"
                )
        self.assertEqual(result["phrasecrate"]["status"], "missing")
        self.assertIsNone(result["phrasecrate"]["metrics"])


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
