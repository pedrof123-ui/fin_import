"""Dry-run the peak/trough rubric across the universe (PLAN_CYCLE_AWARENESS.md Phase 3).

Reports the fire rate of each side among CYCLICAL names, per-condition and pairwise rates so a
degenerate condition cannot hide, and the both-sides clash count. The plan's gate: neither side
may fire on more than roughly a quarter of cyclical names.

Rebuilding the cyclicality verdict for 2,600 tickers takes a few minutes, so the inputs are
cached; pass --refresh to rebuild.

Usage: uv run python scripts/cycle_position_calibration.py [--refresh]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.cycle_data import (  # noqa: E402
    CYCLICAL, MID, PEAK, TROUGH, classify_cyclicality, evaluate_cycle_position,
)

_DATA = Path(__file__).parent.parent / "data"
_CACHE = _DATA / "cycle_position_calibration_inputs.json"

NAMED = ["AAPL", "MSFT", "KO", "PG", "COST", "V", "WMT", "JNJ", "UNH",
         "MU", "CLF", "NUE", "F", "GM", "DAL", "UAL", "OXY", "DVN", "AAL",
         "CAT", "DE", "SLB", "CCL", "LYB"]


def build_inputs() -> list[dict]:
    conn = duckdb.connect(str(_DATA / "historic_fundamentals.duckdb"), read_only=True)
    ps = {r[0]: r[1:] for r in conn.execute("""
        SELECT ticker, current_ttm_eps, forward_12m_eps, earn_growth_1yr, earn_cagr_3yr,
               current_operating_margin, operating_margin_5y_median, current_pe,
               pe_rolling_5yr_median, rev_growth_1yr
        FROM pe_stats
    """).fetchall()}
    hist = {r[0]: r[1:] for r in conn.execute("""
        WITH now AS (
            SELECT ticker, median(shares) AS shares_now FROM monthly_pe
            WHERE shares > 0 AND month_end_date >= CURRENT_DATE - INTERVAL 12 MONTHS
            GROUP BY ticker
        ), adj AS (
            SELECT m.ticker, m.ttm_eps * m.shares / n.shares_now AS eps
            FROM monthly_pe m JOIN now n USING (ticker)
            WHERE m.ttm_eps IS NOT NULL AND m.shares > 0 AND n.shares_now > 0
              AND m.month_end_date >= CURRENT_DATE - INTERVAL 5 YEARS
        )
        SELECT ticker, MAX(eps), AVG(eps) FROM adj GROUP BY ticker
    """).fetchall()}
    conn.close()

    out = []
    tickers = sorted(set(ps) & set(hist))
    for i, t in enumerate(tickers, 1):
        p, h = ps[t], hist[t]
        out.append(dict(
            ticker=t, verdict=classify_cyclicality(t).verdict,
            ttm_eps=p[0], fwd_eps=p[1], earn_growth_1yr=p[2], earn_cagr_3yr=p[3],
            operating_margin=p[4], operating_margin_median=p[5], pe=p[6], pe_median=p[7],
            rev_growth_1yr=p[8], eps_max=h[0], eps_midcycle=h[1],
        ))
        if i % 500 == 0:
            print(f"  ... {i}/{len(tickers)}", flush=True)
    return out


def score(row: dict):
    return evaluate_cycle_position(
        row["verdict"],
        **{k: row[k] for k in ("ttm_eps", "fwd_eps", "earn_growth_1yr", "earn_cagr_3yr",
                               "operating_margin", "operating_margin_median", "pe", "pe_median",
                               "rev_growth_1yr", "eps_max", "eps_midcycle")},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="rebuild the cached inputs")
    args = ap.parse_args()

    if args.refresh or not _CACHE.exists():
        print("building inputs (classifying the universe, a few minutes)...")
        rows = build_inputs()
        _CACHE.write_text(json.dumps(rows))
    else:
        rows = json.loads(_CACHE.read_text())
        print(f"using cached inputs ({_CACHE.name}; --refresh to rebuild)")

    cyc = [r for r in rows if r["verdict"] == CYCLICAL]
    scored = {r["ticker"]: score(r) for r in rows}
    print(f"\nuniverse={len(rows)}  cyclical={len(cyc)}")

    def rate(rs, position):
        return sum(scored[r["ticker"]].position == position for r in rs) / len(rs)

    print("\n=== fire rate among CYCLICAL names (plan gate: each side <= ~25%) ===")
    peak_rate, trough_rate = rate(cyc, PEAK), rate(cyc, TROUGH)
    print(f"  PEAK   {peak_rate * 100:5.1f}%")
    print(f"  TROUGH {trough_rate * 100:5.1f}%")
    print(f"  MID    {rate(cyc, MID) * 100:5.1f}%")

    print("\n=== per-condition rate among CYCLICAL names (a degenerate condition shows here) ===")
    for side in ("peak", "trough"):
        counts: dict[str, int] = {}
        for r in cyc:
            s = scored[r["ticker"]]
            for c in getattr(s, f"{side}_met"):
                counts[c] = counts.get(c, 0) + 1
        print(f"  {side}:")
        for c, n in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {n / len(cyc) * 100:5.1f}%  {c[:88]}")

    print("\n=== pairwise co-firing among CYCLICAL names (catches the cond1/cond4 failure) ===")
    for side in ("peak", "trough"):
        met = {r["ticker"]: set(getattr(scored[r["ticker"]], f"{side}_met")) for r in cyc}
        conds = sorted({c for s in met.values() for c in s})
        pairs = []
        for a, b in itertools.combinations(conds, 2):
            n = sum(a in s and b in s for s in met.values())
            pairs.append((n / len(cyc), a, b))
        print(f"  {side} — worst 3 pairs:")
        for frac, a, b in sorted(pairs, reverse=True)[:3]:
            print(f"    {frac * 100:5.1f}%  {a[:42]} + {b[:42]}")

    clash = [r["ticker"] for r in cyc if scored[r["ticker"]].notes
             and any("contradictory" in n for n in scored[r["ticker"]].notes)]
    print(f"\n=== both sides firing: {len(clash)} of {len(cyc)} cyclicals ===")
    if clash:
        print(f"  {clash[:20]}")

    print("\n=== named tickers ===")
    for t in NAMED:
        r = next((x for x in rows if x["ticker"] == t), None)
        if not r:
            continue
        s = scored[t]
        print(f"  {t:6} {r['verdict']:22} {s.position:14} "
              f"peak {len(s.peak_met)}/5  trough {len(s.trough_met)}/5")

    ok = peak_rate <= 0.27 and trough_rate <= 0.27
    print("\n" + ("PASS: both sides within the plan's fire-rate gate"
                  if ok else "FAIL: a side fires too broadly — tighten before proceeding"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
