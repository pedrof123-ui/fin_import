# Archive

Completed plan documents, moved here rather than deleted. Git preserves deleted files, but nobody
greps git history — these stay greppable, and several memory notes and code comments reference
them by name for their rejected-alternative reasoning.

**Nothing here is current.** Every file records the state at the time it was closed. Check the
code before acting on anything in this directory.

| File | Subject | Closed |
|---|---|---|
| `PLAN.md` | AI Researcher — technical analyst, earnings data, peer grounding, multi-agent pipeline, frontend | all 6 phases |
| `AI_RESEARCHER_IMPROVEMENT_PLAN.md` | The larger AI Researcher improvement programme | all phases |
| `AI_RESEARCHER_IMPROVEMENT.md` | The source request behind the two plans above | superseded |
| `PLAN_CYCLE_AWARENESS.md` | Peak/trough cycle detection and report framing | Phases 0-9, 2026-08-19 (7 dropped, 9.4 declined) |
| `PLAN_DISPERSION.md` | Analyst estimate dispersion feature | 2026-08-13 |
| `PLAN_MDA.md` | MD&A extraction and backfill | 2026-07-29 |
| `PLAN_ML_COMPS_TRIANGULATION.md` | ML comps as a triangulation anchor in the AI Researcher | 2026-08-14 |
| `CANSLIM_FACTOR_TEST_PLAN.md` | CANSLIM factor bundle — **tested and rejected** | 2026-07-24 |
| `DCF_SCREENER_PLAN.md` | Screener `dcf_upside` filter — live in `api/screener_router.py` | shipped |
| `DCF_VISION.md` | Original AV Financials / AV DCF tab request | see note below |
| `PLAN_DCF_ACCURACY.md` | DCF accuracy measurement — **factor tested and rejected >=$1B**; guard 10x→2.5x | 2026-08-22 |

**`DCF_VISION.md`'s terminal-growth item is RESOLVED (2026-08-22) — and the note that used to
stand here was wrong.** It said `dcf/model.py::_default_terminal_growth(income_df)` ignoring its
argument was "the fingerprint of logic that was removed or never landed". It is not. The spec —
terminal growth = median historical annual revenue growth — is **unimplementable**: across 1,831
tickers holding both a WACC and >=5 annual growth observations, median historical revenue growth
is 9.1% against a median WACC of 9.66%, so 45.8% of companies would have g >= WACC (Gordon Growth
breaks entirely) and 52.5% would produce a broken or absurd terminal value. 80.8% exceed nominal
GDP, impossible as perpetual growth.

The flat `DEFAULT_TERMINAL_GROWTH = 0.03` is the correct rejection of a bad spec, and the unused
argument is deliberate. A bounded variant was built and A/B'd and made no measurable difference
(delta IC +0.00003); it was removed rather than left as dead code. Reasoning lives above
`_default_terminal_growth` in `dcf/model.py`, and the measurement in
`docs/dcf_upside_factor_test.md`.

`DCF_VISION.md`'s other decision — risk-free rate from `fred.duckdb` — is live (`dcf/data.py`,
`dcf/wacc.py`).

**`PLAN_DCF_ACCURACY.md` is closed but has a live successor.** Its findings are summarised in
`docs/dcf_upside_factor_test.md` alongside the other factor verdicts; the open questions it could
not answer moved to `features/dcf/PLAN_DCF_FOLLOWUP.md`.
