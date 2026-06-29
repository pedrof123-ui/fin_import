"""Rebuild all sector_stats rows (full recompute)."""

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HF_DB = str(ROOT / "data" / "historic_fundamentals.duckdb")
AV_DB = str(os.environ.get("AV_FINANCIALS_DB_PATH", ROOT / "data" / "av_financials.duckdb"))

from historic_fundamentals.db import HistoricFundamentalsDB
from historic_fundamentals.sector import compute_sector_stats

db = HistoricFundamentalsDB(HF_DB)
log.info("Computing sector stats (full rebuild)…")
df = compute_sector_stats(db.conn, AV_DB, full_rebuild=True)
if df.empty:
    log.warning("No sector stats computed — check company_overview data")
else:
    n = db.upsert_sector_stats(df)
    log.info("Upserted %d rows (%d sectors, %d industries)",
             n,
             len(df[df["group_type"] == "sector"]),
             len(df[df["group_type"] == "industry"]))
db.close()
