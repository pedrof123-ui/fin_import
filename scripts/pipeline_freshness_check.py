"""Verify the monthly fundamentals pipeline (av_update -> hf_update -> ... -> score_live)
actually completed today, not just that cron launched it.

Runs from cron a few hours after the pipeline's 00:05 ET start, on the same day. A
2026-09-01 incident showed the pipeline can be silently killed mid-run (e.g. a reboot)
with zero trace in its own log -- this is a watchdog for that failure mode, checked
against a completely independent signal (the CSV score_live.py writes as its last step)
rather than trusting pipeline.log alone.

Sends a Telegram alert only on failure; silent on success. Exits non-zero on failure so
cron_wrap.sh's own failure handling (cron_failures.log + desktop notify) also fires.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
PIPELINE_LOG = REPO / "logs" / "pipeline.log"
DOCS_DIR = REPO / "docs"
TELEGRAM_ENV = Path.home() / ".claude" / "channels" / "telegram" / ".env"
CHAT_ID = "8351706654"


def bot_token() -> str:
    for line in TELEGRAM_ENV.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"TELEGRAM_BOT_TOKEN not found in {TELEGRAM_ENV}")


def send_telegram(msg: str) -> None:
    r = requests.post(f"https://api.telegram.org/bot{bot_token()}/sendMessage",
                       json={"chat_id": CHAT_ID, "text": msg}, timeout=30)
    if not (r.ok and r.json().get("ok")):
        print(f"telegram send failed: {r.status_code} {r.text[:200]}")


def check() -> str | None:
    """Returns None if the pipeline completed today, else a failure reason."""
    today = date.today()

    todays_csv = sorted(DOCS_DIR.glob(f"live_scores_{today:%Y%m%d}_*.csv"))
    if not todays_csv:
        return (f"No live_scores_{today:%Y%m%d}_*.csv found in docs/ -- "
                f"score_live.py (the pipeline's last step) never completed today.")

    if not PIPELINE_LOG.exists():
        return "pipeline.log does not exist."

    log_date = date.fromtimestamp(PIPELINE_LOG.stat().st_mtime)
    if log_date != today:
        return (f"pipeline.log last modified {log_date}, not today -- "
                f"a live_scores CSV exists but doesn't look like it came from today's pipeline run.")

    tail = PIPELINE_LOG.read_text()[-2000:]
    if "Pipeline Complete" not in tail:
        return "pipeline.log was updated today but doesn't end with the 'Pipeline Complete' banner -- looks interrupted."

    return None


def main() -> None:
    failure = check()
    if failure is None:
        print("Pipeline freshness check: OK")
        return

    msg = f"Pipeline freshness check FAILED ({date.today()}): {failure}"
    print(msg)
    send_telegram(msg)
    sys.exit(1)


if __name__ == "__main__":
    main()
