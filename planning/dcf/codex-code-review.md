# DCF Feature and Web App Code Review

Reviewed code paths:

- `dcf/`
- `api/dcf_router.py`
- `web/app/page.tsx`
- `web/components/Dcf*.tsx`
- `web/lib/dcf-types.ts`
- `web/lib/formatField.ts`

## Findings

### Medium: Mixed period-order conventions make latest-period access fragile

`dcf/data.py` loads quarterly statements oldest to newest, but `dcf/wacc.py` and `dcf/model.py` read `.iloc[-1]` for debt, cash, and diluted shares:

- `dcf/data.py:22-33`
- `dcf/wacc.py:74-85`
- `dcf/model.py:355-367`

This is internally correct today because the quarterly query sorts ascending. The risk is that the annual loader sorts newest first while the quarterly loader sorts oldest first, and the code relies on both conventions in different places. This is easy to break and hard to spot because `.iloc[0]` means latest in annual data while `.iloc[-1]` means latest in quarterly data.

Recommended fix: normalize each loader to expose a clear convention, or add helper functions such as `latest_row(df)` and use them everywhere. Add tests that assert the latest debt, cash, and shares are used.

### High: CapEx history is misaligned by index

`forecast_assumptions()` sorts income and cash flow annual data independently, resets both indexes, then computes:

- `dcf/forecaster.py:202-203`
- `dcf/forecaster.py:236-238`

Because both frames are reset to index `0..n`, `inc_a["revenue"].reindex(cf_a.index)` aligns by row position, not by period. If any year is missing from cash flow or income, CapEx percentages are silently paired with the wrong revenue year. That directly changes projected FCFF.

Recommended fix: merge annual income and cash flow by `period_end_date` before deriving ratios. Use the same approach for any cross-statement ratios.

### High: User-entered revenue growth overrides do not update the displayed base revenue consistently

`merge_overrides()` reconstructs forecast revenue levels from the overridden growth rates, but it derives the starting revenue from the first model forecast and the first model growth:

- `dcf/forecaster.py:332-336`

That works only if the first model forecast was itself calculated from the true last historical revenue and if no upstream forecast inconsistency exists. The DCF engine already knows the actual latest annual revenue in `run_dcf()` at `dcf/model.py:317-330`, but that value is not passed into `merge_overrides()`.

Recommended fix: make `merge_overrides()` accept the latest actual annual revenue, then compound user growth assumptions from that explicit base. Add a focused test where Y1 growth is overridden and expected Y1 revenue is `last_actual_revenue * (1 + override)`.

### Medium: Blank or invalid UI inputs can send non-finite values to the API

`parsePct()` returns `NaN` for blank/non-numeric values, and `handleUpdate()` directly places parsed values into the request body:

- `web/lib/formatField.ts:22-24`
- `web/components/DcfViewer.tsx:137-160`

`JSON.stringify()` converts `NaN` to `null`, which Pydantic accepts for optional fields. In practice, clearing a field does not mean "use model default" in an obvious way, and malformed values can silently become null instead of showing a validation error. `parseFloat()` fields for beta/DSO/DPO/DIO have the same issue.

Recommended fix: parse form values through helpers that return `undefined` for blank values and reject invalid non-blank values before POST. The backend should also validate realistic ranges for rates, beta, and working capital days.

### Medium: The DCF tab can fail immediately after an FY import while quarterly import runs in the background

After an FY import, the page loads annual financials, marks the ticker loaded, and starts quarterly import asynchronously:

- `web/app/page.tsx:76-97`

The DCF route requires at least 8 quarterly income periods:

- `dcf/data.py:35-40`

So a user can click the DCF tab before the background quarterly import finishes and get an avoidable 422 error. The status message says quarters are being fetched, but the DCF tab is still enabled.

Recommended fix: disable or defer the DCF tab while `quartersStatus` indicates an in-flight quarterly import, or have the DCF viewer show a loading/pending state until the quarterly import completes.

### Medium: API turns unexpected model failures into raw 500 detail strings

`api/dcf_router.py` catches every unexpected exception and returns `detail=str(exc)`:

- `api/dcf_router.py:95-100`

This leaks internal implementation details to the UI and makes different failure classes indistinguishable. It is especially noticeable because the DCF model has several external data dependencies: price DB, FRED DB, yfinance, and financial statements.

Recommended fix: let expected DCF data issues raise `ValueError` with user-safe messages, log unexpected exceptions server-side, and return a generic 500 message to the client.

### Low: Hard-coded external database paths make DCF less portable

`dcf/data.py` hard-codes price and FRED database paths:

- `dcf/data.py:5-6`

This matches the current machine layout, but it makes the app brittle outside this workspace and makes tests awkward.

Recommended fix: read these from config or environment variables with the current paths as defaults.

### Low: DCF model code lacks direct tests

Existing tests cover API/import behavior, but I did not find DCF-specific tests for forecast alignment, WACC inputs, override behavior, or UI request parsing.

Recommended fix: add focused Python tests for `forecast_assumptions()`, `merge_overrides()`, `compute_wacc()`, and `run_dcf()` using small in-memory DataFrames or a test DuckDB. Add a small frontend unit test for request body construction if a test framework is introduced.

## Overall Assessment

The feature is coherent and the code is mostly easy to follow. The backend separates data loading, forecasting, WACC, and valuation cleanly, and the web UI gives the user a useful editable DCF surface without too much ceremony.

The main risks are correctness risks rather than structure risks. Cross-statement alignment, implicit row-order conventions, and override compounding can materially change valuation output while still producing plausible-looking numbers. I would address those before adding more DCF features.

## Suggested Fix Order

1. Merge cross-statement historical data by `period_end_date` before deriving ratios.
2. Make latest-period access explicit instead of relying on mixed `.iloc[0]` / `.iloc[-1]` conventions.
3. Pass latest actual revenue into `merge_overrides()` and test override compounding.
4. Harden UI parsing and backend validation for user-entered assumptions.
5. Gate the DCF tab until quarterly data is ready after FY imports.
6. Move external DB paths to config/env defaults.

No tests were run for this review; this was a static code assessment.
