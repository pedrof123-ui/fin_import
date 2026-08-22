#!/usr/bin/env python3
"""
Reconstruct historical DCF valuations as-of past quarter-ends, for the DCF accuracy
measurement (features/dcf/PLAN_DCF_ACCURACY.md Phase 2).

Intrinsic value is recomputed QUARTERLY, because that is when the statement inputs change.
`dcf_upside = intrinsic / price - 1` is then built MONTHLY at analysis time by carrying the
most recent available intrinsic value against each month's price -- which yields a monthly
panel comparable to the gauntlet that rejected CANSLIM/Greenblatt/MD&A, at quarterly compute
cost, and mirrors production (dcf_results is rebuilt periodically, screened against live
prices continuously).

Every run is point-in-time: statements by the repo's reporting-lag convention, price and
risk-free rate by date, beta by computed_date, and no analyst estimates (earnings_estimates
only begins 2026-05-10, so any analyst input here would be from the future). This is the
MECHANICAL model, which diverges from the shipped one by ~29% median intrinsic value.

Output is one parquet per as-of date, so the job is resumable -- an interrupted run re-runs
only the dates it has not finished.

WARNING when comparing two panels: a panel bakes in whatever dcf/model.py constants were live
when it was built, not just the rule under test. Comparing a panel built at
MAX_INTRINSIC_TO_PRICE=10 against one built at 2.5 shows an 18.8pp "coverage collapse" that has
nothing to do with the rule being tested. Rebuild the baseline under the current constants, and
sanity-check by confirming that ticker-dates which errored in one panel do not carry an IDENTICAL
intrinsic value in the other -- if they do, the difference is a guard, not the rule.

Usage:
    uv run scripts/reconstruct_dcf_panel.py --benchmark      # time a sample, write nothing
    uv run scripts/reconstruct_dcf_panel.py                  # full panel, 6 workers
    uv run scripts/reconstruct_dcf_panel.py --workers 4 --start 2010 --end 2024
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH  # noqa: E402

log = logging.getLogger(__name__)

OUT_DIR = ROOT / "data" / "dcf_reconstruction"

# Deliberately looser than the gauntlet's UNIVERSE_DEFAULTS. This decides only where compute
# is spent; Phase 3 applies the exact filters (including ADV liquidity) at test time. A panel
# can always be filtered down later, never up.
MIN_MARKET_CAP = 1_000_000_000
MIN_PRICE = 5.0


def quarter_ends(start_year: int, end_year: int) -> list[date]:
    return [
        date(y, m, d)
        for y in range(start_year, end_year + 1)
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
    ]


def universe_at(as_of: date, hf_db: str, min_cap: float = MIN_MARKET_CAP,
                max_cap: float | None = None) -> list[str]:
    """Tickers investable on as_of, from monthly_pe's point-in-time price and shares.

    `max_cap` lets a run cover only a cap band, so extending the panel downward is additive
    rather than recomputing the names already done at a higher floor.

    monthly_pe.shares goes transiently wrong around splits, so this market cap is slightly
    noisy. Measured 2026-08-21: 21 ticker-dates on the 60 quarter-ends, 0.028% of the panel.
    It only decides where compute is spent -- the DCF reads diluted_shares from the AV
    statements, never from monthly_pe -- so a spuriously included ticker still gets a
    correct valuation.
    """
    conn = duckdb.connect(hf_db, read_only=True)
    try:
        rows = conn.execute(
            f"""
            WITH latest AS (
                SELECT max(month_end_date) AS d FROM monthly_pe WHERE month_end_date <= ?
            )
            SELECT ticker
            FROM monthly_pe, latest
            WHERE month_end_date = latest.d
              AND price >= ?
              AND shares IS NOT NULL
              AND price * shares >= ?
              {"AND price * shares < ?" if max_cap is not None else ""}
            ORDER BY ticker
            """,
            [as_of, MIN_PRICE, min_cap] + ([max_cap] if max_cap is not None else []),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def _run_one_date(as_of: date, hf_db: str, out_dir: str = str(OUT_DIR),
                  min_cap: float = MIN_MARKET_CAP,
                  max_cap: float | None = None) -> tuple[date, int, int, float]:
    """Reconstruct one as-of date. Runs in a worker process; writes its own parquet."""
    from dcf.model import run_dcf_av

    t0 = time.time()
    out = Path(out_dir)
    tickers = universe_at(as_of, hf_db, min_cap=min_cap, max_cap=max_cap)
    rows = []
    for ticker in tickers:
        try:
            r = run_dcf_av(ticker, as_of=as_of)
            rows.append({
                "ticker": ticker,
                "as_of": as_of,
                "intrinsic_value_per_share": r.intrinsic_value_per_share,
                "price_at_computation": r.current_price,
                "wacc": r.wacc_detail.wacc,
                "beta_raw": r.wacc_detail.beta_raw,
                "risk_free_rate": r.wacc_detail.risk_free_rate,
                "terminal_growth_rate": r.terminal_growth_rate,
                "tv_pct_enterprise_value": r.tv_pct_enterprise_value,
                "enterprise_value": r.enterprise_value,
                "net_debt": r.net_debt,
                "diluted_shares": r.diluted_shares,
                "analyst_years_applied": r.analyst_years_applied,
                "status": "ok",
                "error_message": None,
            })
        except Exception as e:
            rows.append({
                "ticker": ticker, "as_of": as_of,
                "intrinsic_value_per_share": None, "price_at_computation": None,
                "wacc": None, "beta_raw": None, "risk_free_rate": None,
                "terminal_growth_rate": None, "tv_pct_enterprise_value": None,
                "enterprise_value": None, "net_debt": None, "diluted_shares": None,
                "analyst_years_applied": None,
                "status": "error", "error_message": str(e)[:500],
            })

    df = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / f"{as_of.isoformat()}.parquet", index=False)
    n_ok = int((df["status"] == "ok").sum()) if not df.empty else 0
    return as_of, len(df), n_ok, time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconstruct as-of DCF valuations (PLAN_DCF_ACCURACY Phase 2).")
    ap.add_argument("--start", type=int, default=2010)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--hf-db", default=HF_DB_PATH)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--min-market-cap", type=float, default=MIN_MARKET_CAP)
    ap.add_argument("--max-market-cap", type=float, default=None,
                    help="Upper bound, to cover only a cap band (extension runs)")
    ap.add_argument("--benchmark", action="store_true",
                    help="Time 50 tickers on one as-of date and exit without writing the panel")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.benchmark:
        from dcf.model import run_dcf_av
        as_of = date(2015, 6, 30)
        tickers = universe_at(as_of, args.hf_db)
        sample = tickers[:50]
        print(f"universe at {as_of}: {len(tickers)} tickers; timing {len(sample)}...", flush=True)
        t0 = time.time()
        n_ok = 0
        for t in sample:
            try:
                run_dcf_av(t, as_of=as_of)
                n_ok += 1
            except Exception:
                pass
        per = (time.time() - t0) / len(sample)
        total_h = per * len(tickers) * len(quarter_ends(args.start, args.end)) / 3600
        print(f"{per:.3f}s/ticker ({n_ok}/{len(sample)} ok)")
        print(f"projected full panel: {total_h:.1f}h single-threaded, "
              f"{total_h / args.workers:.1f}h across {args.workers} workers")
        return

    dates = quarter_ends(args.start, args.end)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    todo = [d for d in dates if not (out / f"{d.isoformat()}.parquet").exists()]
    print(f"{len(dates)} as-of dates, {len(dates) - len(todo)} already done, {len(todo)} to run "
          f"on {args.workers} workers", flush=True)

    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(_run_one_date, d, args.hf_db, args.out_dir,
                      args.min_market_cap, args.max_market_cap): d
            for d in todo
        }
        for fut in as_completed(futures):
            as_of, n, n_ok, elapsed = fut.result()
            done += 1
            print(f"[{done}/{len(todo)}] {as_of}  {n_ok}/{n} ok  {elapsed:.0f}s "
                  f"(total {(time.time() - t0) / 60:.0f}m)", flush=True)

    print(f"\nDone in {(time.time() - t0) / 60:.1f} min. Panel: {out}")


if __name__ == "__main__":
    main()
