"""Export pending MD&A pairs (keys + capped texts) to a zstd parquet for the RunPod sweep.

Reuses pairs_sql(form)/system_prompt(form) from the nightly script and asserts the remote
script's prompt/schema are byte-identical for that form, so remote results merge back
without any regime split.

Usage: uv run scripts/mda_remote/export_pending.py [--form 10-K|10-Q]
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
    args = ap.parse_args()
    form = args.form

    assert remote_sweep.system_prompt(form) == sweep.system_prompt(form), \
        f"remote SYSTEM prompt drifted from nightly script for {form}"

    out = REPO / "data" / f"mda_pairs_pending_{form.lower().replace('-', '')}.parquet"

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
            where (p.ticker, p.fiscal_period_end) not in (
                select ticker, fiscal_period_end from feats.mda_features
                where prompt_version = '{sweep.PROMPT_VERSION}' and form = '{form}')
        ) to '{out}' (format parquet, compression zstd)
    """)
    n, mb = con.execute(
        f"select count(*), round(sum(strlen(cur_text) + strlen(prior_text)) / 1e6) from '{out}'"
    ).fetchone()
    con.close()
    size_mb = out.stat().st_size / 1e6
    print(f"{out}: {n} pending pairs, {mb:.0f} MB text, {size_mb:.0f} MB compressed")


if __name__ == "__main__":
    main()
