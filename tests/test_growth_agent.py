import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import json
import os

from growth_agent.ai import analyze, log_line
from growth_agent.metrics import CWS_ACTIVE_USER_DEFINITIONS
from growth_agent.report import build_actions, render
from growth_agent.collectors import (
    _cws_url,
    _period,
    _utc_range,
    collect_chrome_web_store,
    collect_cloudflare,
    collect_github,
    collect_x,
)
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
                    "1d": {key: {"value": None, "state": "pending", "observed_days": 0, "expected_days": 1} for key in ("installs", "uninstalls", "impressions", "page_views")},
                    "7d": {key: {"value": 7, "state": "partial", "observed_days": 5, "expected_days": 7} for key in ("installs", "uninstalls", "impressions", "page_views")},
                    "30d": {key: {"value": 30, "state": "observed", "observed_days": 30, "expected_days": 30} for key in ("installs", "uninstalls", "impressions", "page_views")},
                },
                "conversion_rate": {"1d": None, "7d": None, "30d": 0.1},
                "active_users": {
                    "users": {"value": 4, "date": "2026-10-21", "trend_7d": [{"date": "2026-10-21", "value": 4}]},
                    "users_7d": {"value": 3, "date": "2026-10-21", "trend_7d": []},
                },
                "source_breakdown_30d": {
                    "install_source": {
                        "values": {"organic": {"installs": 3}},
                        "state": "partial", "observed_days": 2, "expected_days": 30,
                    },
                    "utm_source": {
                        "values": None, "state": "missing", "observed_days": 0, "expected_days": 30,
                    },
                },
                "data_source": "chrome_web_store_api_v2",
                "last_updated_at": "2026-10-22T05:00:00+09:00",
            },
        }
        snapshot["actions"] = []
        report = render(snapshot, [])
        self.assertIn("### Chrome Web Store公式Metrics", report)
        self.assertIn("インストール数／ストアPV（参考比率）", report)
        self.assertIn("| 1d | — (pending) |", report)
        self.assertIn("7 (5/7日)", report)
        self.assertIn("10.0%", report)
        self.assertIn("Daily active users: 4 (2026-10-21)", report)
        self.assertIn(CWS_ACTIVE_USER_DEFINITIONS["users"]["description"], report)
        self.assertIn(CWS_ACTIVE_USER_DEFINITIONS["users_7d"]["description"], report)
        self.assertIn("10-21:4", report)
        self.assertIn("install-source（30日、取得 2/30日、状態: partial）", report)
        self.assertIn("UTM source（30日、取得 0/30日、状態: missing）", report)

    def test_jst_day_is_converted_to_utc(self):
        start, end = _utc_range(date(2026, 10, 22), "Asia/Tokyo")
        self.assertEqual(start, "2026-10-21T15:00:00Z")
        self.assertEqual(end, "2026-10-22T15:00:00Z")

    def test_cws_utm_source_query_uses_page_views_only(self):
        url = _cws_url(
            "publisher", "item", date(2026, 10, 1), date(2026, 10, 30),
            ("page-views",), "utm-source",
        )
        self.assertIn("metrics=page-views", url)
        self.assertIn("dimensions=utm-source", url)
        self.assertNotIn("metrics=installs", url)

    def test_pending_daily_state_is_preserved_in_one_day_period(self):
        daily = {"2026-10-22": {
            "installs": None, "uninstalls": None, "impressions": None, "page_views": None,
            "metric_states": {
                "installs": "pending", "uninstalls": "pending",
                "impressions": "pending", "page_views": "pending",
            },
        }}
        period = _period(daily, date(2026, 10, 22), 1)
        self.assertEqual(period["installs"]["state"], "pending")
        self.assertEqual(period["installs"]["pending_days"], 1)
        self.assertIsNone(period["installs"]["value"])

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
            {"metricRows": [{
                "date": {"year": 2026, "month": 10, "day": 21},
                "dimensionValues": ["newsletter"],
                "metricValues": [{"metric": "page-views", "value": "5"}],
            }]},
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
        self.assertEqual(metrics["periods"]["1d"]["installs"]["state"], "pending")
        self.assertEqual(metrics["periods"]["30d"]["installs"]["value"], 2)
        self.assertEqual(metrics["periods"]["30d"]["installs"]["observed_days"], 2)
        self.assertIsNone(metrics["periods"]["30d"]["uninstalls"]["value"])
        self.assertEqual(metrics["periods"]["30d"]["uninstalls"]["observed_days"], 0)
        self.assertEqual(metrics["source_breakdown_30d"]["install_source"]["values"]["organic"]["installs"], 2)
        self.assertEqual(metrics["source_breakdown_30d"]["install_source"]["observed_days"], 1)
        self.assertEqual(metrics["source_breakdown_30d"]["utm_source"]["values"]["newsletter"]["page_views"], 5)
        self.assertEqual(len(raw["base"]), 2)
        self.assertIn("2026-10-21", normalized["daily"])
        self.assertIn("pageToken=next", request_json.call_args_list[1].args[0])
        install_source_url = request_json.call_args_list[2].args[0]
        utm_source_url = request_json.call_args_list[3].args[0]
        self.assertIn("metrics=installs", install_source_url)
        self.assertIn("dimensions=install-source", install_source_url)
        self.assertNotIn("page-views", install_source_url)
        self.assertIn("metrics=page-views", utm_source_url)
        self.assertIn("dimensions=utm-source", utm_source_url)
        self.assertNotIn("metrics=installs", utm_source_url)
        self.assertNotIn("token", json.dumps(raw))

    @patch("growth_agent.collectors.request_json")
    def test_cws_dimension_failure_is_failed_not_zero(self, request_json):
        config = {"products": [{"slug": "phrasecrate", "item_id": "item"}]}
        request_json.side_effect = [
            {"metricRows": [{
                "date": {"year": 2026, "month": 10, "day": 21},
                "metricValues": [{"metric": "installs", "value": "1"}],
            }]},
            {"metricRows": []},
            RuntimeError("UTM API unavailable"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"CWS_ACCESS_TOKEN": "token", "CWS_PUBLISHER_ID": "publisher"}):
                result = collect_chrome_web_store(
                    config, date(2026, 10, 22), Path(directory), Path(directory) / "history"
                )
        source = result["phrasecrate"]
        utm = source["metrics"]["source_breakdown_30d"]["utm_source"]
        self.assertEqual(source["status"], "partial")
        self.assertEqual(utm["state"], "failed")
        self.assertIsNone(utm["values"])
        self.assertIn("UTM API unavailable", utm["error"])

    @patch("growth_agent.collectors.request_json")
    def test_cws_requery_updates_delayed_data_across_report_dates(self, request_json):
        config = {"products": [{"slug": "phrasecrate", "item_id": "item"}]}
        request_json.side_effect = [
            {"metricRows": [
                {"date": {"year": 2026, "month": 10, "day": 21}, "metricValues": [{"metric": "installs", "value": "1"}]},
            ]},
            {"metricRows": [
                {"date": {"year": 2026, "month": 10, "day": 21}, "dimensionValues": ["organic"], "metricValues": [{"metric": "installs", "value": "1"}]},
            ]},
            {"metricRows": []},
            {"metricRows": [
                {"date": {"year": 2026, "month": 10, "day": 21}, "metricValues": [{"metric": "installs", "value": "3"}]},
                {"date": {"year": 2026, "month": 10, "day": 22}, "metricValues": [{"metric": "installs", "value": "2"}]},
            ]},
            {"metricRows": [
                {"date": {"year": 2026, "month": 10, "day": 21}, "dimensionValues": ["organic"], "metricValues": [{"metric": "installs", "value": "3"}]},
                {"date": {"year": 2026, "month": 10, "day": 22}, "dimensionValues": ["ads"], "metricValues": [{"metric": "installs", "value": "2"}]},
            ]},
            {"metricRows": []},
        ]
        secret = "ya29.sensitive-access-token"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "history"
            with patch.dict(os.environ, {"CWS_ACCESS_TOKEN": secret, "CWS_PUBLISHER_ID": "publisher"}):
                first = collect_chrome_web_store(config, date(2026, 10, 22), root / "imports", storage)
                second = collect_chrome_web_store(config, date(2026, 10, 23), root / "imports", storage)
            normalized = json.loads((storage / "normalized/phrasecrate.json").read_text())
            persisted = "\n".join(path.read_text() for path in storage.rglob("*.json"))
            raw_dates = {
                path.stem for path in (storage / "raw/phrasecrate").glob("*.json")
            }

        self.assertEqual(first["phrasecrate"]["metrics"]["daily"]["2026-10-21"]["installs"], 1)
        self.assertEqual(second["phrasecrate"]["metrics"]["daily"]["2026-10-21"]["installs"], 3)
        self.assertEqual(normalized["daily"]["2026-10-21"]["installs"], 3)
        self.assertEqual(normalized["daily"]["2026-10-22"]["installs"], 2)
        self.assertIn("2026-09-23", normalized["daily"])
        self.assertEqual(second["phrasecrate"]["metrics"]["periods"]["30d"]["installs"]["value"], 5)
        self.assertEqual(second["phrasecrate"]["metrics"]["source_breakdown_30d"]["install_source"]["observed_days"], 2)
        self.assertNotIn(secret, persisted)
        self.assertNotIn("Authorization", persisted)
        self.assertNotIn("Bearer", persisted)
        self.assertEqual(raw_dates, {"2026-10-22", "2026-10-23"})

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

    @patch("growth_agent.collectors.request_json")
    def test_x_collector_still_returns_public_metrics(self, request_json):
        request_json.side_effect = [
            {"data": {"id": "user-1"}},
            {"data": [{"id": "post-1", "text": "hello", "public_metrics": {
                "impression_count": 100, "like_count": 5, "retweet_count": 2,
                "reply_count": 1, "quote_count": 0,
            }}]},
        ]
        with patch.dict(os.environ, {"X_BEARER_TOKEN": "x-token"}):
            result = collect_x({"username": "errrt0dev"}, date(2026, 10, 22), "Asia/Tokyo")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"]["posts"], 1)
        self.assertEqual(result["metrics"]["impressions"], 100)
        self.assertEqual(result["metrics"]["engagement_rate"], 0.08)

    @patch("growth_agent.collectors.request_json")
    def test_github_collector_still_returns_repository_and_traffic_metrics(self, request_json):
        request_json.side_effect = [
            {"stargazers_count": 7, "open_issues_count": 2},
            [{"sha": "abc"}],
            [
                {"created_at": "2026-10-21T16:00:00Z"},
                {"created_at": "2026-10-21T17:00:00Z", "pull_request": {}},
            ],
            {"views": [{"timestamp": "2026-10-21T00:00:00Z", "count": 10, "uniques": 4}]},
            {"clones": [{"timestamp": "2026-10-21T00:00:00Z", "count": 3, "uniques": 2}]},
        ]
        with patch.dict(os.environ, {"GITHUB_TOKEN": "github-token"}):
            result = collect_github({"repositories": ["errrt/errrt.github.io"]}, date(2026, 10, 22), "Asia/Tokyo")
        repo = result["metrics"]["errrt/errrt.github.io"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(repo["metrics"]["stars"], 7)
        self.assertEqual(repo["metrics"]["commits"], 1)
        self.assertEqual(repo["metrics"]["issues_created"], 1)
        self.assertEqual(repo["metrics"]["prs_created"], 1)
        self.assertEqual(repo["metrics"]["views"], 10)


class AIAnalysisTests(unittest.TestCase):
    def _cws_snapshot(self, healthy=True):
        store = {
            "status": "ok" if healthy else "error",
            "error": None if healthy else "API failed",
            "metrics": {"data_source": "chrome_web_store_api_v2"} if healthy else None,
        }
        return {"sources": {"chrome_web_store": {
            "phrasecrate": store,
            "tab-parcel": store,
        }}}

    def _mixed_cws_snapshot(self):
        return {"sources": {"chrome_web_store": {
            "phrasecrate": {
                "status": "partial",
                "error": "utm-source dimension failed",
                "metrics": {"data_source": "chrome_web_store_api_v2"},
            },
            "tab-parcel": {
                "status": "partial",
                "error": "Official API failed; using CSV fallback",
                "metrics": {"data_source": "official_csv"},
            },
        }}}

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
    def test_ai_context_describes_current_cws_pipeline(self, request_json):
        result_json = {
            "summary": "要約", "observations": ["観測"],
            "hypotheses": ["仮説"], "opportunities": ["機会"],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze({"sources": {}}, [])
        self.assertEqual(analysis["status"], "ok")
        body = request_json.call_args.kwargs["body"]
        context = json.loads(body["input"])
        contract = context["data_contract"]["chrome_web_store"]
        self.assertIn("API v2", contract["primary_source"])
        self.assertIn("Fallback only", contract["csv_role"])
        self.assertIn("Removed", contract["public_listing_scraping"])
        self.assertIn("observed_days/expected_days", contract["partial_periods"])
        self.assertIn("never numeric zero", contract["missing_values"])
        self.assertEqual(contract["active_users"], {
            definition["api_metric"]: definition["description"]
            for definition in CWS_ACTIVE_USER_DEFINITIONS.values()
        })
        self.assertIn("do not recommend", contract["recommendation_guard"])
        self.assertIn("Do not estimate churn, retention, conversion", contract["inference_guard"])
        self.assertIn("Never compare or divide installs by users/users-7d", contract["inference_guard"])
        self.assertIn("data_contract", body["instructions"])
        self.assertIn("古いhistory", body["instructions"])
        self.assertIn("installsとusers/users-7dを直接比較", body["instructions"])

    @patch("growth_agent.ai.request_json")
    def test_actual_periodic_csv_recommendation_is_removed_but_valid_item_remains(self, request_json):
        invalid = (
            "Chrome Web Storeの公式Developer Dashboardからanalytics CSVを定期取得して"
            "imports/chrome-web-store/へ投入し、APIの欠損日を補完する。"
        )
        valid = "公式API v2の部分集計は取得済み日数を併記して評価する。"
        result_json = {
            "summary": "公式APIを分析した。", "observations": ["観測は正常。"],
            "hypotheses": ["原因は断定しない。"], "opportunities": [invalid, valid],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(self._cws_snapshot(), [])
        self.assertEqual(analysis["result"]["opportunities"], [valid])
        validation = analysis["diagnostics"]["content_validation"]
        self.assertEqual(validation["status"], "sanitized")
        self.assertEqual(validation["removed"], [{"field": "opportunities", "reason": "unnecessary_csv_workflow"}])

    @patch("growth_agent.ai.request_json")
    def test_public_listing_users_misclassification_is_removed(self, request_json):
        invalid = "公開表示のactive usersは4から5へ増加した。"
        valid = "usersは公式API v2のアクティブユーザー指標である。"
        result_json = {
            "summary": "公式APIを分析した。", "observations": [invalid, valid],
            "hypotheses": ["原因は断定しない。"], "opportunities": ["取得を継続する。"],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(self._cws_snapshot(), [])
        self.assertEqual(analysis["result"]["observations"], [valid])
        self.assertIn("users_misclassified_as_public_listing", {
            item["reason"] for item in analysis["diagnostics"]["content_validation"]["removed"]
        })

    @patch("growth_agent.ai.request_json")
    def test_actual_public_user_count_misclassification_is_removed(self, request_json):
        invalid = (
            "Chrome Web Storeの公開ユーザー数や部分的なinstalls観測は、APIの遅延やpartial観測日の不足"
            "（observed_days < expected_days）による部分集計であり、未観測日をゼロとして扱うべきではない可能性がある。"
        )
        valid = "users/users-7dは公式API v2のアクティブユーザー指標であり、欠損日はゼロではない。"
        result_json = {
            "summary": "公式APIを分析した。", "observations": ["観測は正常。"],
            "hypotheses": [invalid, valid], "opportunities": ["取得を継続する。"],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        snapshot = self._cws_snapshot()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(snapshot, [])

        self.assertEqual(analysis["result"]["hypotheses"], [valid])
        self.assertEqual(analysis["diagnostics"]["content_validation"]["removed"], [{
            "field": "hypotheses", "reason": "users_misclassified_as_public_listing",
        }])
        snapshot["sources"].update({
            "cloudflare": {"status": "missing", "error": "not configured", "metrics": None},
            "x": {"status": "missing", "error": "not configured", "metrics": None},
            "github": {"status": "ok", "error": None, "metrics": {}},
        })
        snapshot.update({"date": "2026-10-31", "analysis": analysis, "actions": []})
        report = render(snapshot, [])
        self.assertNotIn(invalid, report)
        self.assertIn(valid, report)

    @patch("growth_agent.ai.request_json")
    def test_public_user_wording_variants_are_removed(self, request_json):
        invalid = [
            "公開ユーザー数が増加した。",
            "公開利用者数は5人だった。",
            "公開アクティブユーザー数が前日を上回った。",
        ]
        result_json = {
            "summary": "公式APIを分析した。", "observations": invalid,
            "hypotheses": ["原因は断定しない。"], "opportunities": ["取得を継続する。"],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(self._cws_snapshot(), [])

        self.assertEqual(analysis["result"]["observations"], [
            "Chrome Web Store指標は公式API v2の取得状態とobserved_days/expected_daysに基づき評価します。"
        ])
        self.assertEqual(analysis["diagnostics"]["content_validation"]["removed_count"], 3)

    @patch("growth_agent.ai.request_json")
    def test_correct_public_user_negations_are_preserved(self, request_json):
        valid = [
            "users/users-7dは公開ユーザー数ではなく、公式API v2のアクティブユーザー指標である。",
            "アクティブユーザーは公開ストアページの表示人数ではありません。",
            "公開されているAPI仕様に従いusersを取得した。",
        ]
        result_json = {
            "summary": "公式APIを分析した。", "observations": valid,
            "hypotheses": ["原因は断定しない。"], "opportunities": ["取得を継続する。"],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(self._cws_snapshot(), [])

        self.assertEqual(analysis["result"]["observations"], valid)
        self.assertEqual(analysis["diagnostics"]["content_validation"]["status"], "passed")

    @patch("growth_agent.ai.request_json")
    def test_unsupported_retention_calculation_is_removed(self, request_json):
        invalid = "installs 70をusers 2で割り、継続率を2.9%と算出できる。"
        result_json = {
            "summary": "公式APIを分析した。", "observations": ["部分集計である。"],
            "hypotheses": [invalid], "opportunities": ["取得を継続する。"],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(self._cws_snapshot(), [])
        self.assertNotIn(invalid, analysis["result"]["hypotheses"])
        self.assertEqual(analysis["result"]["hypotheses"], [
            "欠損・pendingがある期間は原因を断定せず、次回取得で補完状況を確認します。"
        ])

    @patch("growth_agent.ai.request_json")
    def test_csv_explanations_respect_api_collection_state(self, request_json):
        healthy_text = "公式API v2が正常なためCSV取得は不要である。"
        failed_text = "API障害時はCSVをフォールバックとして投入する。"
        base = {"summary": "分析", "observations": ["観測"], "hypotheses": ["仮説"]}
        request_json.side_effect = [
            self._completed_payload(json.dumps({**base, "opportunities": [healthy_text]}, ensure_ascii=False)),
            self._completed_payload(json.dumps({**base, "opportunities": [failed_text]}, ensure_ascii=False)),
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            healthy = analyze(self._cws_snapshot(True), [])
            failed = analyze(self._cws_snapshot(False), [])
        self.assertEqual(healthy["result"]["opportunities"], [healthy_text])
        self.assertEqual(healthy["diagnostics"]["content_validation"]["status"], "passed")
        self.assertEqual(failed["result"]["opportunities"], [failed_text])
        self.assertEqual(failed["diagnostics"]["content_validation"]["status"], "not_applicable")

    @patch("growth_agent.ai.request_json")
    def test_partial_official_api_data_enables_content_validation(self, request_json):
        invalid = "Tab Parcelのanalytics CSVを定期取得して投入する。"
        valid = "Tab Parcelの公式API v2で取得できた基本指標を継続して評価する。"
        result_json = {
            "summary": "分析", "observations": ["観測"], "hypotheses": ["仮説"],
            "opportunities": [invalid, valid],
        }
        snapshot = self._cws_snapshot()
        snapshot["sources"]["chrome_web_store"]["tab-parcel"] = {
            "status": "partial",
            "error": "utm-source dimension failed",
            "metrics": {"data_source": "chrome_web_store_api_v2"},
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(snapshot, [])

        self.assertEqual(analysis["result"]["opportunities"], [valid])
        validation = analysis["diagnostics"]["content_validation"]
        self.assertEqual(validation["status"], "sanitized")
        self.assertEqual(validation["healthy_products"], ["phrasecrate", "tab-parcel"])

    @patch("growth_agent.ai.request_json")
    def test_mixed_product_states_only_protect_official_api_product(self, request_json):
        phrasecrate_csv = "PhraseCrateのanalytics CSVを定期取得して投入する。"
        phrasecrate_scraping = "PhraseCrateの公開ストアページのスクレイピングを再開して取得する。"
        phrasecrate_auth = "PhraseCrateのChrome Web Store API認証再設定を行う。"
        tab_parcel_fallback = "Tab ParcelはAPI障害時にCSVをフォールバックとして投入する。"
        result_json = {
            "summary": "分析", "observations": ["観測"], "hypotheses": ["仮説"],
            "opportunities": [phrasecrate_csv, phrasecrate_scraping, phrasecrate_auth],
        }
        fallback_result = {
            **result_json,
            "opportunities": [phrasecrate_csv, tab_parcel_fallback],
        }
        request_json.side_effect = [
            self._completed_payload(json.dumps(result_json, ensure_ascii=False)),
            self._completed_payload(json.dumps(fallback_result, ensure_ascii=False)),
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            sanitized = analyze(self._mixed_cws_snapshot(), [])
            fallback = analyze(self._mixed_cws_snapshot(), [])

        self.assertEqual(sanitized["diagnostics"]["content_validation"]["healthy_products"], ["phrasecrate"])
        self.assertEqual(
            {item["reason"] for item in sanitized["diagnostics"]["content_validation"]["removed"]},
            {"unnecessary_csv_workflow", "public_listing_scraping", "unnecessary_api_reconfiguration"},
        )
        self.assertNotIn(phrasecrate_csv, fallback["result"]["opportunities"])
        self.assertEqual(fallback["result"]["opportunities"], [tab_parcel_fallback])

    @patch("growth_agent.ai.request_json")
    def test_csv_fallback_only_does_not_enable_api_content_validation(self, request_json):
        csv_action = "Chrome Web Storeのanalytics CSVを定期取得して投入する。"
        result_json = {
            "summary": "分析", "observations": ["観測"], "hypotheses": ["仮説"],
            "opportunities": [csv_action],
        }
        fallback_store = {
            "status": "partial",
            "error": "Official API failed; using CSV fallback",
            "metrics": {"data_source": "official_csv"},
        }
        snapshot = {"sources": {"chrome_web_store": {
            "phrasecrate": fallback_store,
            "tab-parcel": fallback_store,
        }}}
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(snapshot, [])

        self.assertEqual(analysis["result"]["opportunities"], [csv_action])
        self.assertEqual(analysis["diagnostics"]["content_validation"]["status"], "not_applicable")
        self.assertEqual(analysis["diagnostics"]["content_validation"]["healthy_products"], [])

    @patch("growth_agent.ai.request_json")
    def test_scraping_and_unnecessary_cws_reauthentication_are_removed(self, request_json):
        scraping = "Chrome Web Store公開ページのスクレイピングを再開して指標を取得する。"
        reauthentication = "Chrome Web Store APIの認証再設定を行う。"
        valid = "公式API v2の取得を継続する。"
        result_json = {
            "summary": "分析", "observations": ["観測"], "hypotheses": ["仮説"],
            "opportunities": [scraping, reauthentication, valid],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(self._cws_snapshot(), [])
        self.assertEqual(analysis["result"]["opportunities"], [valid])
        self.assertEqual(
            {item["reason"] for item in analysis["diagnostics"]["content_validation"]["removed"]},
            {"public_listing_scraping", "unnecessary_api_reconfiguration"},
        )

    @patch("growth_agent.ai.request_json")
    def test_sanitized_output_keeps_report_schema_and_hides_invalid_items(self, request_json):
        invalid_csv = "analytics CSVを定期取得してアップロードする。"
        invalid_users = "usersは公開ストアの公開表示人数である。"
        invalid_retention = "installsとusersを比較して継続率50%と計算する。"
        result_json = {
            "summary": "公式APIを分析した。", "observations": [invalid_users],
            "hypotheses": [invalid_retention], "opportunities": [invalid_csv],
        }
        request_json.return_value = self._completed_payload(json.dumps(result_json, ensure_ascii=False))
        snapshot = self._cws_snapshot()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5-mini"}):
            analysis = analyze(snapshot, [])
        self.assertTrue(all(analysis["result"][field] for field in ("observations", "hypotheses", "opportunities")))

        snapshot["sources"].update({
            "cloudflare": {"status": "missing", "error": "not configured", "metrics": None},
            "x": {"status": "missing", "error": "not configured", "metrics": None},
            "github": {"status": "ok", "error": None, "metrics": {}},
        })
        snapshot.update({"date": "2026-10-31", "analysis": analysis, "actions": []})
        report = render(snapshot, [])
        self.assertIn("内容検証: 不適切なAI項目を3件除外", report)
        self.assertNotIn(invalid_csv, report)
        self.assertNotIn(invalid_users, report)
        self.assertNotIn(invalid_retention, report)
        self.assertIn("公式API v2の取得を継続", report)

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
