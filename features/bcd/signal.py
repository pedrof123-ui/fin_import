"""BCD-lite structural mispricing signal.

Simplified Bakshi-Chen-Dong model price using three observable inputs:
  - TTM EPS (realized earnings)
  - EPS growth G(t): trailing 1yr realized growth (or analyst 1yr forward where available)
  - 30-year Treasury yield R(t) as the long-rate anchor

Model price: P_model = ttm_eps * (1 + G) / (R + ERP - g_terminal)
Mispricing:  Misp = (price - P_model) / P_model

Positive Misp = overpriced; negative Misp = underpriced.
"""

_ERP = 0.055          # equity risk premium (Damodaran estimate)
_TERMINAL_GROWTH = 0.03  # long-run nominal growth (real GDP + inflation)
_MISP_CLIP = 3.0      # clip extreme values at ±3σ


def compute_bcd_lite_misp(
    ttm_eps: float,
    earnings_growth: float,
    price: float,
    dgs30: float,
    erp: float = _ERP,
    terminal_growth: float = _TERMINAL_GROWTH,
    misp_clip: float = _MISP_CLIP,
) -> float | None:
    """Compute BCD-lite mispricing ratio.

    Args:
        ttm_eps: Trailing twelve-month EPS (must be positive).
        earnings_growth: 1-year EPS growth rate as decimal (e.g. 0.10 for 10%).
                         Use trailing realized growth or analyst 1yr forward consensus.
        price: Current stock price (must be positive).
        dgs30: 30-year Treasury yield as decimal (e.g. 0.048 for 4.8%).
        erp: Equity risk premium. Defaults to 5.5% (Damodaran).
        terminal_growth: Long-run terminal growth rate. Defaults to 3%.
        misp_clip: Clip output to [-clip, +clip].

    Returns:
        Mispricing ratio, or None if inputs are invalid or transversality fails.
    """
    if not (ttm_eps > 0 and price > 0 and dgs30 > 0):
        return None
    discount_rate = dgs30 + erp
    spread = discount_rate - terminal_growth  # always > 0 when dgs30 > 0
    if spread <= 0:
        return None
    # Two-stage: earn one year at earnings_growth, then perpetuity at terminal_growth.
    # Denominator uses terminal_growth only, so any earnings_growth is valid.
    forward_eps = ttm_eps * (1.0 + earnings_growth)
    if forward_eps <= 0:
        return None
    model_price = forward_eps / spread
    misp = (price - model_price) / model_price
    return float(max(-misp_clip, min(misp_clip, misp)))
