import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .ai import analyze, log_line
from .collectors import collect_chrome_web_store, collect_cloudflare, collect_github, collect_x
from .report import build_actions, load_history, render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("growth-agent.json"))
    parser.add_argument("--date", help="Report date in YYYY-MM-DD; defaults to yesterday in configured timezone")
    parser.add_argument("--output-dir", type=Path, default=Path("growth-output"))
    parser.add_argument("--history-dir", type=Path, default=Path("growth-history"))
    parser.add_argument("--imports-dir", type=Path, default=Path("imports/chrome-web-store"))
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    timezone = ZoneInfo(config.get("timezone", "Asia/Tokyo"))
    report_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(timezone).date() - timedelta(days=1)
    # Re-running a date must not compare against or deduplicate against its own prior output.
    history = [item for item in load_history(args.history_dir) if item.get("date") != report_date.isoformat()]
    snapshot = {
        "schema_version": 1,
        "date": report_date.isoformat(),
        "generated_at": datetime.now(timezone).isoformat(),
        "sources": {
            "cloudflare": collect_cloudflare(config["cloudflare"], report_date, config.get("timezone", "Asia/Tokyo")),
            "chrome_web_store": collect_chrome_web_store(
                config["chrome_web_store"], report_date, args.imports_dir, config.get("timezone", "Asia/Tokyo")
            ),
            "x": collect_x(config["x"], report_date, config.get("timezone", "Asia/Tokyo")),
            "github": collect_github(config["github"], report_date, config.get("timezone", "Asia/Tokyo")),
        },
    }
    snapshot["analysis"] = analyze(snapshot, history)
    print(log_line(snapshot["analysis"]))
    snapshot["actions"] = build_actions(snapshot, history)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.history_dir.mkdir(parents=True, exist_ok=True)
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    (args.output_dir / "snapshot.json").write_text(snapshot_json, encoding="utf-8")
    (args.output_dir / "report.md").write_text(render(snapshot, history), encoding="utf-8")
    (args.history_dir / f"{report_date.isoformat()}.json").write_text(snapshot_json, encoding="utf-8")
    print(args.output_dir / "report.md")


if __name__ == "__main__":
    main()
