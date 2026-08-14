"""Export the 'maintained' guidance_direction bucket (keys + capped texts) for a targeted
re-extraction pass on a stronger model. These pairs already have an 8B result in
mda_features -- this is a *rerun*, not a pending-gap fill (see export_pending.py for that).

Usage: uv run scripts/mda_remote/export_maintained.py [--form 10-K|10-Q] [--model qwen3:8b]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mda_feature_sweep as sweep  # noqa: E402
import remote_sweep  # noqa: E402

assert remote_sweep.SCHEMA == sweep.SCHEMA, "remote SCHEMA drifted from nightly script"
assert remote_sweep.PROMPT_VERSION == sweep.PROMPT_VERSION
assert remote_sweep.CHAR_CAP == sweep.CHAR_CAP
assert remote_sweep.NUM_CTX == sweep.NUM_CTX


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", default="10-K", choices=["10-K", "10-Q"])
    ap.add_argument("--model", default="qwen3:8b")
    args = ap.parse_args()
    form = args.form

    assert remote_sweep.system_prompt(form) == sweep.system_prompt(form), \
        f"remote SYSTEM prompt drifted from nightly script for {form}"

    out = REPO / "data" / f"mda_pairs_maintained_{form.lower().replace('-', '')}.parquet"

    con = duckdb.connect()
    con.execute(f"attach '{sweep.FILINGS_DB}' as filings (read_only)")
    con.execute(f"attach '{sweep.FEATURES_DB}' as feats (read_only)")
    con.execute("use filings")
    con.execute(f"""
        copy (
            with pairs as ({sweep.pairs_sql(form)})
            select p.*,
                   left(ca.mda_text, {sweep.CHAR_CAP}) as cur_text,
                   left(cb.mda_text, {sweep.CHAR_CAP}) as prior_text
            from pairs p
            join mda_filings ca on ca.ticker = p.ticker and ca.form = '{form}'
                 and ca.fiscal_period_end = p.fiscal_period_end and ca.status = 'ok'
            join mda_filings cb on cb.ticker = p.ticker and cb.form = '{form}'
                 and cb.fiscal_period_end = p.prior_fiscal_period_end and cb.status = 'ok'
            where (p.ticker, p.fiscal_period_end) in (
                select ticker, fiscal_period_end from feats.mda_features
                where prompt_version = '{sweep.PROMPT_VERSION}' and form = '{form}'
                  and model = '{args.model}' and guidance_direction = 'maintained')
        ) to '{out}' (format parquet, compression zstd)
    """)
    n, mb = con.execute(
        f"select count(*), round(sum(strlen(cur_text) + strlen(prior_text)) / 1e6) from '{out}'"
    ).fetchone()
    con.close()
    size_mb = out.stat().st_size / 1e6
    print(f"{out}: {n} maintained-bucket pairs, {mb:.0f} MB text, {size_mb:.0f} MB compressed")


if __name__ == "__main__":
    main()
