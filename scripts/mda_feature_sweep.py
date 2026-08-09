"""Nightly MD&A feature extraction sweep (local Ollama, qwen3:8b).

Extracts five structured features from each post-2016 10-K MD&A pair (current + prior
year) into data/mda_features.duckdb. Designed to run from cron 23:00-03:00 and be
killed/resumed freely. See docs/mda_feature_sweep_spec.md.

Usage:
  uv run scripts/mda_feature_sweep.py                     # nightly run until 03:00
  uv run scripts/mda_feature_sweep.py --limit 3           # smoke test
  uv run scripts/mda_feature_sweep.py --validate          # discrimination gate, no writes
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import requests

REPO = Path(__file__).resolve().parent.parent
FILINGS_DB = REPO / "data" / "mda_filings.duckdb"
FEATURES_DB = REPO / "data" / "mda_features.duckdb"
STATUS_FILE = REPO / "data" / "mda_sweep_status.json"
OLLAMA_LOG = REPO / "logs" / "ollama_serve.log"

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:8b"
PROMPT_VERSION = "v1.1"
CHAR_CAP = 24_000
NUM_CTX = 16_384
MAX_CONSECUTIVE_ERRORS = 5

SCHEMA = {
    "type": "object",
    "properties": {
        "guidance_direction": {"type": "string", "enum": ["raised", "maintained", "lowered", "withdrawn", "none_given"]},
        "tone_delta": {"type": "integer", "minimum": -2, "maximum": 2},
        "new_risk_language": {"type": "integer", "minimum": 0, "maximum": 3},
        "specificity": {"type": "integer", "minimum": 0, "maximum": 3},
        "hedging_change": {"type": "integer", "minimum": -2, "maximum": 2},
        "rationale": {"type": "string"},
    },
    "required": ["guidance_direction", "tone_delta", "new_risk_language", "specificity", "hedging_change", "rationale"],
}

SYSTEM = """You compare two consecutive annual MD&A sections from the same company's 10-K filings.
Extract exactly these features as JSON:
- guidance_direction: the direction of management's forward-looking OUTLOOK LANGUAGE in the CURRENT filing vs the PRIOR filing. MD&A rarely contains formal numeric guidance; judge the outlook management describes (demand, margins, investment plans, expected results). Weigh the business trajectory management actually reports, not its phrasing: accelerating growth and expanding investment indicate raised; deterioration, restructuring, impairments or weakening demand indicate lowered even when phrased optimistically; steady continuation indicates maintained. New risk disclosures alone do not lower the outlook if the described trajectory is strong (raised/maintained/lowered/withdrawn/none_given).
- tone_delta: change in management tone from PRIOR to CURRENT (-2 much more negative .. +2 much more positive)
- new_risk_language: extent of risk/uncertainty language in CURRENT that is absent from PRIOR (0 none .. 3 substantial new risks)
- specificity: how concrete the CURRENT filing is (named figures, quantified drivers) (0 pure boilerplate .. 3 highly specific)
- hedging_change: change in hedged/cautious phrasing from PRIOR to CURRENT (-2 much less hedged .. +2 much more hedged)
- rationale: one sentence citing the main evidence
Base every answer only on the supplied text."""

# ticker -> fiscal year of the CURRENT filing (None = latest available pair)
VALIDATION_PAIRS = [("NVDA", None), ("UPS", None), ("KO", None), ("ENVA", None), ("ANET", None),
                    ("PTON", 2022), ("LUMN", 2022), ("VFC", 2024)]

PAIRS_SQL = """
with ok as (
    select * from mda_filings
    where status = 'ok' and mda_text is not null and form = '10-K'
)
select a.ticker, a.fiscal_period_end, b.fiscal_period_end, a.filing_date, a.accession_no,
       a.char_count, b.char_count
from ok a
join ok b
  on a.ticker = b.ticker
 and b.fiscal_period_end between a.fiscal_period_end - interval 400 day
                             and a.fiscal_period_end - interval 330 day
where a.filing_date >= date '2016-01-01'
qualify row_number() over (
    partition by a.ticker, a.fiscal_period_end
    order by abs(date_diff('day', b.fiscal_period_end, a.fiscal_period_end) - 365)
) = 1
"""


def log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def ensure_ollama() -> None:
    try:
        requests.get(f"{OLLAMA_URL}/api/version", timeout=3)
        return
    except requests.RequestException:
        pass
    log("ollama not responding, starting server")
    import os
    env = {**os.environ, "OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}
    OLLAMA_LOG.parent.mkdir(exist_ok=True)
    with open(OLLAMA_LOG, "a") as f:
        subprocess.Popen(["ollama", "serve"], env=env, stdout=f, stderr=f, start_new_session=True)
    for _ in range(30):
        time.sleep(1)
        try:
            requests.get(f"{OLLAMA_URL}/api/version", timeout=3)
            return
        except requests.RequestException:
            continue
    raise RuntimeError("could not start ollama serve")


def extract(cur_text: str, prior_text: str) -> dict:
    user = (f"PRIOR-YEAR MD&A:\n{prior_text[:CHAR_CAP]}\n\n"
            f"CURRENT-YEAR MD&A:\n{cur_text[:CHAR_CAP]}\n\nExtract the features.")
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "format": SCHEMA,
        "think": True,
        "stream": False,
        "keep_alive": "15m",
        "options": {"num_ctx": NUM_CTX, "temperature": 0},
    }, timeout=600)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def init_features_db() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(FEATURES_DB))
    con.execute("""
        create table if not exists mda_features (
            ticker varchar, form varchar, fiscal_period_end date, prompt_version varchar,
            prior_fiscal_period_end date, filing_date date, accession_no varchar,
            guidance_direction varchar, tone_delta tinyint, new_risk_language tinyint,
            specificity tinyint, hedging_change tinyint, rationale varchar,
            model varchar, cur_chars integer, prior_chars integer,
            elapsed_s double, extracted_at timestamp,
            primary key (ticker, form, fiscal_period_end, prompt_version)
        )
    """)
    return con


def fetch_pending() -> tuple[list, int]:
    """Returns (pending pair keys newest-first, total pair count). Text is deliberately
    not fetched here: all pairs' MD&A at once is several GB. Connections are closed
    before returning so no lock is held during the sweep."""
    con = duckdb.connect(str(FILINGS_DB), read_only=True)
    pairs = con.execute(PAIRS_SQL).fetchall()
    con.close()
    fcon = init_features_db()
    done = {(t, f) for t, f in fcon.execute(
        "select ticker, fiscal_period_end from mda_features where prompt_version = ?",
        [PROMPT_VERSION]).fetchall()}
    fcon.close()
    pending = [p for p in pairs if (p[0], p[1]) not in done]
    pending.sort(key=lambda p: p[3], reverse=True)
    return pending, len(pairs)


def fetch_texts(ticker: str, fpe, prior_fpe) -> tuple[str, str]:
    """Short-lived read-only connection per pair: never holds the filings DB open for
    more than one lookup (the weekly mda_update cron needs write access to it)."""
    con = duckdb.connect(str(FILINGS_DB), read_only=True)
    q = "select mda_text from mda_filings where ticker=? and form='10-K' and fiscal_period_end=?"
    cur = con.execute(q, [ticker, fpe]).fetchone()[0]
    prior = con.execute(q, [ticker, prior_fpe]).fetchone()[0]
    con.close()
    return cur, prior


def write_status(**kw) -> None:
    STATUS_FILE.write_text(json.dumps(kw, indent=2, default=str))


def window_deadline(window_end: str) -> datetime:
    h, m = map(int, window_end.split(":"))
    end = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    if end <= datetime.now():
        end += timedelta(days=1)
    return end


def run_sweep(window_end: str, limit: int | None) -> None:
    ensure_ollama()
    pending, total = fetch_pending()
    deadline = window_deadline(window_end) if limit is None else datetime.max
    run_started = datetime.now()
    done_total = total - len(pending)
    log(f"{len(pending)} pairs pending of {total}; window ends {deadline}")

    con = init_features_db()
    tonight = errors = consecutive_errors = 0
    times: list[float] = []
    state = "running"
    last_pair = ""

    def status(state: str) -> None:
        avg = sum(times) / len(times) if times else 40.0
        remaining = len(pending) - tonight
        eta_nights = math.ceil(remaining * avg / (4 * 3600)) if remaining else 0
        write_status(
            run_started=run_started, last_update=datetime.now(), window_end=window_end,
            pairs_total=total, pairs_done_total=done_total + tonight, pairs_tonight=tonight,
            errors_tonight=errors, avg_s_per_pair=round(avg, 1), eta_nights=eta_nights,
            eta_date=(datetime.now() + timedelta(days=eta_nights)).date(),
            last_pair=last_pair, state=state,
        )

    status(state)
    for ticker, fpe, prior_fpe, filing_date, accession, cur_chars, prior_chars in pending:
        if datetime.now() >= deadline:
            log("window end reached")
            break
        if limit is not None and tonight >= limit:
            break
        t0 = time.time()
        try:
            cur, prior = fetch_texts(ticker, fpe, prior_fpe)
            feats = extract(cur, prior)
        except Exception as e:
            errors += 1
            consecutive_errors += 1
            log(f"ERROR {ticker} {fpe}: {e}")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                state = "aborted"
                log("too many consecutive errors, aborting")
                break
            continue
        consecutive_errors = 0
        elapsed = time.time() - t0
        times.append(elapsed)
        con.execute("insert or replace into mda_features values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            ticker, "10-K", fpe, PROMPT_VERSION, prior_fpe, filing_date, accession,
            feats["guidance_direction"], feats["tone_delta"], feats["new_risk_language"],
            feats["specificity"], feats["hedging_change"], feats["rationale"],
            MODEL, cur_chars, prior_chars, round(elapsed, 1), datetime.now(),
        ])
        tonight += 1
        last_pair = f"{ticker} {fpe}"
        log(f"{last_pair} {elapsed:.0f}s {feats['guidance_direction']} tone={feats['tone_delta']:+d}")
        status(state)

    if state == "running":
        state = "finished"
    status(state)
    con.close()
    log(f"done: {tonight} pairs tonight, {errors} errors, state={state}")
    sys.exit(1 if state == "aborted" else 0)


def run_validation() -> None:
    ensure_ollama()
    con = duckdb.connect(str(FILINGS_DB), read_only=True)
    results = {}
    for ticker, year in VALIDATION_PAIRS:
        row = con.execute(
            PAIRS_SQL.replace("where a.filing_date >= date '2016-01-01'",
                              "where a.ticker = ? and (? is null or year(a.fiscal_period_end) = ?)")
            + " order by a.fiscal_period_end desc limit 1",
            [ticker, year, year]).fetchall()
        if not row:
            print(f"{ticker} FY{year}: pair not found")
            sys.exit(1)
        _, fpe, prior_fpe, _, _, _, _ = row[0]
        cur, prior = fetch_texts(ticker, fpe, prior_fpe)
        feats = extract(cur, prior)
        results[ticker] = feats
        print(f"{ticker} ({fpe}): guid={feats['guidance_direction']} tone={feats['tone_delta']:+d} "
              f"new_risk={feats['new_risk_language']} spec={feats['specificity']} hedge={feats['hedging_change']:+d}")
    con.close()

    gates = [
        ("PTON lowered", results["PTON"]["guidance_direction"] == "lowered"),
        ("PTON tone <= -1", results["PTON"]["tone_delta"] <= -1),
        ("VFC tone <= 0", results["VFC"]["tone_delta"] <= 0),
        ("NVDA new_risk >= 2", results["NVDA"]["new_risk_language"] >= 2),
        # positive side: a blowout growth year must not read as deterioration, and the
        # panel must use more than one guidance label (cross-sectional variance)
        ("NVDA not lowered/withdrawn", results["NVDA"]["guidance_direction"] in ("raised", "maintained")),
        ("ENVA not lowered", results["ENVA"]["guidance_direction"] != "lowered"),
        (">= 3 distinct guidance labels", len({r["guidance_direction"] for r in results.values()}) >= 3),
    ]
    failed = [name for name, ok in gates if not ok]
    for name, ok in gates:
        print(f"  gate {'PASS' if ok else 'FAIL'}: {name}")
    sys.exit(1 if failed else 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-end", default="03:00")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    if args.validate:
        run_validation()
    else:
        run_sweep(args.window_end, args.limit)


if __name__ == "__main__":
    main()
