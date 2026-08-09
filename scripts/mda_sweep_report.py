"""Daily Telegram progress report for the MD&A feature sweep.

Runs from cron at 03:10, after the nightly window closes. Reads the status JSON and the
features DB, sends one summary message. Failure states (no run tonight, aborted run) are
reported explicitly. Exits non-zero if the Telegram send fails so cron_wrap.sh alerts.
See docs/mda_feature_sweep_spec.md.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import requests

REPO = Path(__file__).resolve().parent.parent
STATUS_FILE = REPO / "data" / "mda_sweep_status.json"
FEATURES_DB = REPO / "data" / "mda_features.duckdb"
TELEGRAM_ENV = Path.home() / ".claude" / "channels" / "telegram" / ".env"
CHAT_ID = "8351706654"


def bot_token() -> str:
    for line in TELEGRAM_ENV.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"TELEGRAM_BOT_TOKEN not found in {TELEGRAM_ENV}")


def build_message() -> str:
    if not STATUS_FILE.exists():
        return "MD&A sweep: WARNING - no status file, the sweep has never run."
    s = json.loads(STATUS_FILE.read_text())
    last_update = datetime.fromisoformat(s["last_update"])
    lines = [f"MD&A sweep report {datetime.now():%Y-%m-%d}"]
    if datetime.now() - last_update > timedelta(hours=12):
        lines.append(f"WARNING: no sweep ran in the last 12h (last update {last_update:%Y-%m-%d %H:%M}).")
    if s["state"] == "aborted":
        lines.append(f"WARNING: last run ABORTED after {s['errors_tonight']} errors - check logs/mda_feature_sweep.log")
    lines.append(f"Tonight: {s['pairs_tonight']} pairs, {s['errors_tonight']} errors")
    pct = 100 * s["pairs_done_total"] / s["pairs_total"]
    lines.append(f"Total: {s['pairs_done_total']:,}/{s['pairs_total']:,} ({pct:.1f}%)")
    lines.append(f"Avg {s['avg_s_per_pair']}s/pair, ETA {s['eta_date']} ({s['eta_nights']} nights)")
    con = duckdb.connect(str(FEATURES_DB), read_only=True)
    n, latest = con.execute("select count(*), max(extracted_at) from mda_features").fetchone()
    con.close()
    lines.append(f"DB check: {n:,} rows, last write {latest:%Y-%m-%d %H:%M}")
    return "\n".join(lines)


def main() -> None:
    msg = build_message()
    print(msg)
    r = requests.post(f"https://api.telegram.org/bot{bot_token()}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg}, timeout=30)
    if not (r.ok and r.json().get("ok")):
        print(f"telegram send failed: {r.status_code} {r.text[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
