#!/usr/bin/env python3
"""Daily beta refresh. Run after update_prices.py completes.

Add to crontab (30 min after price update):

    30 23 * * 1-5  cd /home/pedro/projects/fin_import2 && uv run features/beta/update_betas.py
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "update_betas.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def main() -> None:
    from features.beta.beta import refresh_betas, WINDOW_2YR, WINDOW_5YR

    log.info("=== beta refresh started ===")
    try:
        n5 = refresh_betas(window_days=WINDOW_5YR)
        log.info("Wrote %d beta rows (5yr weekly)", n5)
        n2 = refresh_betas(window_days=WINDOW_2YR)
        log.info("Wrote %d beta rows (2yr weekly)", n2)
    except Exception:
        log.exception("Beta refresh failed")
        sys.exit(1)
    log.info("=== beta refresh complete ===")


if __name__ == "__main__":
    main()
