"""Concurrent MD&A feature extraction against local Ollama (RunPod variant).

Self-contained: runs on the pod with only requests + duckdb installed. Reads the
pairs parquet exported by export_pending.py, appends one JSON line per pair to the
output file (resumable: already-present keys are skipped on restart).

SYSTEM prompt, SCHEMA, prompt version and sampling options must stay identical to
scripts/mda_feature_sweep.py -- export_pending.py asserts this at export time.

Usage on the pod:
  python3 remote_sweep.py --input pairs.parquet --output results_8b.jsonl --model qwen3:8b --parallel 6
  python3 remote_sweep.py --input pairs.parquet --output results_30b.jsonl --model qwen3:30b-a3b --parallel 4 --sample 300
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import duckdb
import requests

OLLAMA_URL = "http://localhost:11434"
PROMPT_VERSION = "v1.1"
CHAR_CAP = 24_000
NUM_CTX = 16_384
MAX_ERRORS = 100

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

BODY = """Extract exactly these features as JSON:
- guidance_direction: the direction of management's forward-looking OUTLOOK LANGUAGE in the CURRENT filing vs the PRIOR filing. MD&A rarely contains formal numeric guidance; judge the outlook management describes (demand, margins, investment plans, expected results). Weigh the business trajectory management actually reports, not its phrasing: accelerating growth and expanding investment indicate raised; deterioration, restructuring, impairments or weakening demand indicate lowered even when phrased optimistically; steady continuation indicates maintained. New risk disclosures alone do not lower the outlook if the described trajectory is strong (raised/maintained/lowered/withdrawn/none_given).
- tone_delta: change in management tone from PRIOR to CURRENT (-2 much more negative .. +2 much more positive)
- new_risk_language: extent of risk/uncertainty language in CURRENT that is absent from PRIOR (0 none .. 3 substantial new risks)
- specificity: how concrete the CURRENT filing is (named figures, quantified drivers) (0 pure boilerplate .. 3 highly specific)
- hedging_change: change in hedged/cautious phrasing from PRIOR to CURRENT (-2 much less hedged .. +2 much more hedged)
- rationale: one sentence citing the main evidence
Base every answer only on the supplied text."""

FORM_INTRO = {
    "10-K": "You compare two consecutive annual MD&A sections from the same company's 10-K filings.",
    "10-Q": ("You compare two consecutive quarterly MD&A sections from the same company's 10-Q filings, "
             "one year apart (same fiscal quarter, prior year vs current). 10-Q MD&A covers only the "
             "quarter and year-to-date and often incorporates risk factors by reference rather than "
             "restating them -- do not read the absence of restated risk factors as reduced risk."),
}


def system_prompt(form: str) -> str:
    return FORM_INTRO[form] + "\n" + BODY


def log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def extract(model: str, cur_text: str, prior_text: str, form: str) -> dict:
    user = (f"PRIOR-YEAR MD&A:\n{prior_text[:CHAR_CAP]}\n\n"
            f"CURRENT-YEAR MD&A:\n{cur_text[:CHAR_CAP]}\n\nExtract the features.")
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model,
        "messages": [{"role": "system", "content": system_prompt(form)}, {"role": "user", "content": user}],
        "format": SCHEMA,
        "think": True,
        "stream": False,
        "keep_alive": "30m",
        "options": {"num_ctx": NUM_CTX, "temperature": 0},
    }, timeout=900)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def load_pairs(input_path: str, sample: int | None) -> list[dict]:
    q = f"select * from '{input_path}'"
    if sample:
        q += f" order by md5(ticker || cast(fiscal_period_end as varchar)) limit {sample}"
    con = duckdb.connect()
    cols = [d[0] for d in con.execute(q).description]
    rows = [dict(zip(cols, r)) for r in con.execute(q).fetchall()]
    con.close()
    return rows


def done_keys(output: Path) -> set[tuple[str, str]]:
    if not output.exists():
        return set()
    keys = set()
    for line in output.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            keys.add((d["ticker"], d["fiscal_period_end"]))
    return keys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--sample", type=int)
    ap.add_argument("--max-hours", type=float, default=36)
    ap.add_argument("--form", default="10-K", choices=["10-K", "10-Q"])
    args = ap.parse_args()

    out = Path(args.output)
    pairs = load_pairs(args.input, args.sample)
    done = done_keys(out)
    pending = [p for p in pairs if (p["ticker"], str(p["fiscal_period_end"])) not in done]
    log(f"{len(pending)} pending of {len(pairs)} ({len(done)} already in {out.name})")

    deadline = time.time() + args.max_hours * 3600
    errors = 0
    times: list[float] = []

    def work(p: dict) -> dict:
        t0 = time.time()
        feats = extract(args.model, p["cur_text"], p["prior_text"], args.form)
        return {
            "ticker": p["ticker"], "form": args.form,
            "fiscal_period_end": str(p["fiscal_period_end"]),
            "prompt_version": PROMPT_VERSION,
            "prior_fiscal_period_end": str(p["prior_fiscal_period_end"]),
            "filing_date": str(p["filing_date"]), "accession_no": p["accession_no"],
            **{k: feats[k] for k in ("guidance_direction", "tone_delta", "new_risk_language",
                                     "specificity", "hedging_change", "rationale")},
            "model": args.model, "cur_chars": p["cur_chars"], "prior_chars": p["prior_chars"],
            "elapsed_s": round(time.time() - t0, 1),
            "extracted_at": str(datetime.now()),
        }

    with out.open("a") as f, ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(work, p): p for p in pending}
        for n, fut in enumerate(as_completed(futures), 1):
            p = futures[fut]
            if time.time() > deadline:
                log("max-hours reached, stopping")
                ex.shutdown(cancel_futures=True)
                break
            try:
                row = fut.result()
            except Exception as e:
                errors += 1
                log(f"ERROR {p['ticker']} {p['fiscal_period_end']}: {e}")
                if errors >= MAX_ERRORS:
                    log("too many errors, aborting")
                    ex.shutdown(cancel_futures=True)
                    break
                continue
            f.write(json.dumps(row) + "\n")
            f.flush()
            times.append(row["elapsed_s"])
            if n % 25 == 0 or n == len(pending):
                avg = sum(times) / len(times) / max(args.parallel, 1)
                eta_h = (len(pending) - n) * avg / 3600
                log(f"{n}/{len(pending)} avg {avg:.1f}s/pair effective, eta {eta_h:.1f}h, errors {errors}")

    log(f"done: {len(times)} extracted, {errors} errors")


if __name__ == "__main__":
    main()
