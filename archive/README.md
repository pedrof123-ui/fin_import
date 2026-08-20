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

**`DCF_VISION.md` carries one unresolved item.** It specified that terminal growth should default
to the median of historical annual revenue growth. That is **not** what the code does:
`dcf/model.py::_default_terminal_growth(income_df)` ignores its argument and returns a flat
`DEFAULT_TERMINAL_GROWTH = 0.03` for every company. The unused parameter is the fingerprint of
logic that was removed or never landed. Carried into `features/dcf/PLAN_DCF_ACCURACY.md` as an
open question, since a universal 3% terminal growth is itself an accuracy problem. Its other
decision — risk-free rate from `fred.duckdb` — is live (`dcf/data.py`, `dcf/wacc.py`).
