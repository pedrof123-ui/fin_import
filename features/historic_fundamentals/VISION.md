VISION: [IMPLEMENTED]

Goal prices are fair-value price targets implied by trading at the long-term median multiple.
Stored per-month in monthly_pe (full history) and as current values in pe_stats.
Exposed via get_pe_stats() and get_pe_history().

Columns (monthly_pe and pe_stats):
    goal_pe  = ttm_eps x pe_lt_median
    goal_pcf = (ttm_fcf / shares) x pfcf_lt_median
    goal_peg = forward_12m_eps (as-of month) x pe_lt_median
    goal_bv  = (price / pbv) x pbv_lt_median
    goal_2x  = 2 x price
    goal_low = min(avg of valid goals, goal_peg)   valid = non-null and > 0
    goal_high= max of valid goals

Notes:
    - goal_peg is NULL for months without stored earnings_estimates
    - hf_update.py fetches estimates before computing goals so goal_peg uses fresh data
    - Run: uv run scripts/hf_update.py --skip-estimates to back-fill all historical rows

Also added: current_price to pe_stats (latest month-end adjusted close)

