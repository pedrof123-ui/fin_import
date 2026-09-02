"""
PLAN_DEBT_MATURITY.md Phase 0 — coverage check.

Samples tickers across market-cap deciles and sectors, fetches each one's latest
10-K XBRL, and checks whether the two target debt-note concepts are tagged:

  - us-gaap:ScheduleOfDebtInstrumentsTextBlock (per-tranche coupon/maturity/amount)
  - us-gaap:ScheduleOfMaturitiesOfLongTermDebtTableTextBlock (aggregate ladder)

Writes per-ticker results to data/debt_maturity_coverage_sample.csv and a summary
to docs/debt_maturity_coverage.md.

Usage: uv run scripts/debt_maturity_coverage_check.py [--sample-size 90] [--concurrency 5]
"""

import argparse
import asyncio
import os
import time

import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
from edgar import Company, set_identity  # noqa: E402

set_identity(os.getenv("SEC_ID"))

DEBT_INSTRUMENTS_CONCEPT = "us-gaap:ScheduleOfDebtInstrumentsTextBlock"
MATURITIES_CONCEPT = "us-gaap:ScheduleOfMaturitiesOfLongTermDebtTableTextBlock"

AV_DB = "data/av_financials.duckdb"
OUT_CSV = "data/debt_maturity_coverage_sample.csv"
OUT_DOC = "docs/debt_maturity_coverage.md"


def build_sample(sample_size: int, seed: int) -> pd.DataFrame:
    """Stratify by market-cap decile so coverage isn't dominated by mega-caps."""
    con = duckdb.connect(AV_DB, read_only=True)
    df = con.execute(
        """
        select ticker, sector, market_cap
        from (
            select ticker, sector, market_cap,
                   row_number() over (partition by ticker order by fetch_date desc) as rn
            from company_overview
            where market_cap is not null and market_cap > 0
        )
        where rn = 1
        """
    ).fetchdf()
    con.close()

    df["decile"] = pd.qcut(df["market_cap"], 10, labels=False, duplicates="drop")
    per_decile = max(1, sample_size // df["decile"].nunique())
    sample = df.groupby("decile", group_keys=False)[df.columns].apply(
        lambda g: g.sample(min(per_decile, len(g)), random_state=seed)
    )
    return sample.sample(frac=1, random_state=seed).reset_index(drop=True)


def check_ticker(ticker: str) -> dict:
    row = {
        "ticker": ticker,
        "note_found": False,
        "has_debt_instruments_concept": False,
        "has_maturities_concept": False,
        "filing_date": None,
        "error": None,
    }
    try:
        filing = Company(ticker).get_filings(form="10-K", amendments=False).latest()
        if filing is None:
            row["error"] = "no 10-K on file"
            return row
        row["filing_date"] = str(filing.filing_date)
        xb = filing.xbrl()
        facts = xb.facts.to_dataframe()
        concepts = set(facts["concept"])
        row["has_debt_instruments_concept"] = DEBT_INSTRUMENTS_CONCEPT in concepts
        row["has_maturities_concept"] = MATURITIES_CONCEPT in concepts
        row["note_found"] = row["has_debt_instruments_concept"] or row["has_maturities_concept"]
    except Exception as e:
        row["error"] = str(e)[:200]
    return row


async def main(sample_size: int, concurrency: int, seed: int):
    sample = build_sample(sample_size, seed)
    print(f"Sampled {len(sample)} tickers across {sample['decile'].nunique()} market-cap deciles")

    sem = asyncio.Semaphore(concurrency)
    results = []

    async def bounded(i: int, ticker: str, sector: str, market_cap: float, decile: int):
        async with sem:
            t0 = time.time()
            r = await asyncio.to_thread(check_ticker, ticker)
            r["sector"] = sector
            r["market_cap"] = market_cap
            r["decile"] = decile
            elapsed = time.time() - t0
            status = "OK" if r["note_found"] else ("ERR" if r["error"] else "MISS")
            print(f"[{i}/{len(sample)}] {ticker:8s} {status:5s} {elapsed:.1f}s"
                  + (f"  ({r['error']})" if r["error"] else ""))
            results.append(r)

    await asyncio.gather(
        *[
            bounded(i, row.ticker, row.sector, row.market_cap, row.decile)
            for i, row in enumerate(sample.itertuples(), 1)
        ]
    )

    out = pd.DataFrame(results)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")
    write_doc(out)
    print(f"Wrote {OUT_DOC}")


def write_doc(df: pd.DataFrame):
    valid = df[df["error"].isna()]
    n = len(df)
    n_valid = len(valid)
    hit_rate = valid["note_found"].mean() if n_valid else 0.0
    both_rate = (valid["has_debt_instruments_concept"] & valid["has_maturities_concept"]).mean() if n_valid else 0.0

    by_decile = (
        valid.groupby("decile")["note_found"].agg(["mean", "count"]).reset_index()
        if n_valid else pd.DataFrame()
    )
    by_sector = (
        valid.groupby("sector")["note_found"].agg(["mean", "count"]).reset_index()
        if n_valid else pd.DataFrame()
    )
    errors = df[df["error"].notna()]

    lines = [
        "# Debt Maturity Coverage Check (PLAN_DEBT_MATURITY.md Phase 0)",
        "",
        f"Sample: {n} tickers ({n_valid} fetched successfully, {len(errors)} errors).",
        "",
        f"- Overall hit rate (either concept tagged): {hit_rate:.1%}",
        f"- Both concepts tagged: {both_rate:.1%}",
        "",
        "## By market-cap decile (0=smallest, 9=largest)",
        "",
        "| decile | hit rate | n |",
        "|---|---|---|",
    ]
    for _, r in by_decile.iterrows():
        lines.append(f"| {int(r['decile'])} | {r['mean']:.1%} | {int(r['count'])} |")

    lines += ["", "## By sector", "", "| sector | hit rate | n |", "|---|---|---|"]
    for _, r in by_sector.sort_values("mean", ascending=False).iterrows():
        lines.append(f"| {r['sector']} | {r['mean']:.1%} | {int(r['count'])} |")

    if len(errors):
        lines += ["", "## Errors", ""]
        for _, r in errors.iterrows():
            lines.append(f"- {r['ticker']}: {r['error']}")

    lines += ["", "## Go/no-go", "", "(decision pending — fill in after reviewing the numbers above)"]

    with open(OUT_DOC, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sample-size", type=int, default=90)
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    asyncio.run(main(args.sample_size, args.concurrency, args.seed))
