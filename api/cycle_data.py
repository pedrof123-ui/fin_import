"""Cyclicality gate for the AI Researcher's cycle-position analysis.

Decides whether a company exhibits genuinely cyclical behaviour, so the peak/trough
rubric only runs where a cycle position is a meaningful thing to state. Without this
gate the rubric is noise: measured 2026-08-17, the existing peak-earnings conditions
fire on 48% of the universe, flagging AAPL, MSFT, KO, PG and COST as peak-earnings traps.

Method. Cyclicality is co-movement with an industry cycle, not own volatility. A company
whose revenue is erratic for idiosyncratic reasons (a biotech launch, a one-off charge) is
not cyclical; a company whose revenue swings with its industry is. So we build a peer factor
from the company's own industry and measure how much of the company's revenue variation moves
with it:

    systematic amplitude = |beta to peer factor| x stdev(peer factor)

Both inputs are demeaned first, so the factor captures the common *cycle* rather than common
*growth* — otherwise an industry carrying hyper-growth entrants (autos with TSLA/RIVN) reads
as a rising trend rather than a cycle.

Two data notes that shape the implementation:

- Aggregate revenue, never per-share. monthly_pe.shares is transiently wrong around stock
  splits (AAPL reads 56,899M shares in 2020-09 against a true ~17,100M; WMT reads 24,323M in
  2024-01 against ~8,084M), which craters ttm_eps for a few months and looks like a 90%
  earnings collapse. ttm_revenue carries no share count and is unaffected.
- A 7-year window contains COVID, when nearly every company's revenue fell. Single-drawdown
  measures therefore call ~69% of the universe cyclical. Co-movement does not have this
  problem: everyone dipping together is the factor, and amplitude is measured relative to it.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import duckdb
import numpy as np

_DATA_DIR = Path(__file__).parent.parent / "data"
_HIST_FUND_DB = _DATA_DIR / "historic_fundamentals.duckdb"
_AV_FIN_DB = _DATA_DIR / "av_financials.duckdb"

WINDOW_YEARS = 7          # see PLAN_CYCLE_AWARENESS.md Phase 1 for the coverage/survivorship tradeoff
_MIN_MONTHS = 48          # months of revenue the subject needs within the window
_MIN_OVERLAP = 36         # months where subject and factor are both defined
_MIN_PEERS = 8            # smallest usable peer group
AMPLITUDE_MIN = 0.10      # calibrated 2026-08-17; see scripts/cyclicality_calibration.py

CYCLICAL = "CYCLICAL"
NON_CYCLICAL = "NON_CYCLICAL"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


@dataclasses.dataclass
class Cyclicality:
    ticker: str
    verdict: str
    amplitude: float | None = None    # |beta| x factor stdev
    beta: float | None = None         # sensitivity to the peer cycle
    factor_sd: float | None = None    # how cyclical the peer group itself is
    own_sd: float | None = None       # the company's own revenue-growth volatility
    peer_group: str | None = None     # industry or sector the factor was built from
    peer_count: int = 0
    months: int = 0
    reason: str | None = None         # why INSUFFICIENT_HISTORY, when it applies

    @property
    def is_cyclical(self) -> bool:
        return self.verdict == CYCLICAL


def _attach_av(conn) -> None:
    """Attach the av_financials database, tolerating a concurrent attach of the same alias.

    DuckDB shares one catalog across every connection to the same file, so ATTACH IF NOT EXISTS
    is a check-then-act that races: the research fan-out runs these lookups concurrently, and two
    tasks attaching in the same instant both pass the check and the loser raises. Losing the race
    is harmless — the winner's attach is what makes `av` resolvable for every connection — so the
    error is swallowed rather than serialised behind a lock.
    """
    try:
        conn.execute(f"ATTACH IF NOT EXISTS '{_AV_FIN_DB}' AS av (READ_ONLY)")
    except duckdb.BinderException as e:
        if "already exists" not in str(e):
            raise


def _yoy_growth(rev: np.ndarray) -> np.ndarray:
    """Year-over-year log growth of TTM revenue, demeaned so the series carries
    deviation from the company's own trend rather than its growth level."""
    g = np.full(len(rev), np.nan)
    for i in range(12, len(rev)):
        if np.isfinite(rev[i]) and np.isfinite(rev[i - 12]) and rev[i] > 0 and rev[i - 12] > 0:
            g[i] = np.log(rev[i] / rev[i - 12])
    if np.isfinite(g).sum() >= 24:
        g = g - np.nanmean(g)
    return g


def _peer_tickers(conn, ticker: str) -> tuple[list[str], str | None]:
    """Industry peers, falling back to sector when the industry is too thin.

    Peers must actually have price history: company_overview covers ~9,300 tickers against
    monthly_pe's ~2,600, so counting peers on the overview alone lets a narrow industry pass
    the minimum and then build the factor from a handful of usable names.
    """
    row = conn.execute(
        "SELECT sector, industry FROM av.company_overview WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row:
        return [], None
    sector, industry = row
    for column, value in (("industry", industry), ("sector", sector)):
        if not value:
            continue
        peers = [r[0] for r in conn.execute(f"""
            SELECT o.ticker FROM av.company_overview o
            WHERE o.{column} = ? AND o.ticker != ?
              AND EXISTS (SELECT 1 FROM monthly_pe m
                          WHERE m.ticker = o.ticker AND m.ttm_revenue IS NOT NULL
                            AND m.month_end_date >= CURRENT_DATE - INTERVAL {WINDOW_YEARS} YEARS)
        """, [value, ticker]).fetchall()]
        if len(peers) >= _MIN_PEERS:
            return peers, value
    return [], industry or sector


def classify_cyclicality(ticker: str) -> Cyclicality:
    """Classify a ticker as CYCLICAL / NON_CYCLICAL / INSUFFICIENT_HISTORY."""
    ticker = ticker.upper()
    if not _HIST_FUND_DB.exists() or not _AV_FIN_DB.exists():
        return Cyclicality(ticker, INSUFFICIENT_HISTORY, reason="database not found")

    conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
    try:
        _attach_av(conn)
        peers, group = _peer_tickers(conn, ticker)
        if not peers:
            return Cyclicality(ticker, INSUFFICIENT_HISTORY, peer_group=group,
                               reason=f"fewer than {_MIN_PEERS} peers with a known industry/sector")

        rows = conn.execute(f"""
            SELECT ticker, month_end_date, ttm_revenue
            FROM monthly_pe
            WHERE ticker IN ({','.join('?' * (len(peers) + 1))})
              AND month_end_date >= CURRENT_DATE - INTERVAL {WINDOW_YEARS + 1} YEARS
            ORDER BY month_end_date
        """, [ticker] + peers).fetchall()
    finally:
        conn.close()

    dates = sorted({r[1] for r in rows})
    if len(dates) < _MIN_MONTHS + 12:
        return Cyclicality(ticker, INSUFFICIENT_HISTORY, peer_group=group, peer_count=len(peers),
                           reason="not enough monthly history in the window")
    index = {d: i for i, d in enumerate(dates)}

    series: dict[str, np.ndarray] = {}
    for t, d, rev in rows:
        if t not in series:
            series[t] = np.full(len(dates), np.nan)
        if rev is not None and rev > 0:
            series[t][index[d]] = rev

    window = slice(len(dates) - WINDOW_YEARS * 12, len(dates))
    if ticker not in series:
        return Cyclicality(ticker, INSUFFICIENT_HISTORY, peer_group=group, peer_count=len(peers),
                           reason="no revenue history for this ticker")

    subject = _yoy_growth(series[ticker])[window]
    months = int(np.isfinite(subject).sum())
    if months < _MIN_OVERLAP:
        return Cyclicality(ticker, INSUFFICIENT_HISTORY, peer_group=group, peer_count=len(peers),
                           months=months, reason="not enough revenue observations in the window")

    peer_rows = [_yoy_growth(series[p])[window] for p in peers if p in series]
    peer_rows = [p for p in peer_rows if np.isfinite(p).sum() >= _MIN_OVERLAP]
    if len(peer_rows) < _MIN_PEERS:
        return Cyclicality(ticker, INSUFFICIENT_HISTORY, peer_group=group, peer_count=len(peer_rows),
                           months=months, reason=f"fewer than {_MIN_PEERS} peers with usable history")

    factor = np.nanmedian(np.vstack(peer_rows), axis=0)
    both = np.isfinite(subject) & np.isfinite(factor)
    if both.sum() < _MIN_OVERLAP:
        return Cyclicality(ticker, INSUFFICIENT_HISTORY, peer_group=group, peer_count=len(peer_rows),
                           months=months, reason="subject and peer factor barely overlap")

    x, y = factor[both], subject[both]
    var_x = float(x.var())
    if var_x <= 1e-12:
        return Cyclicality(ticker, NON_CYCLICAL, amplitude=0.0, beta=0.0, factor_sd=0.0,
                           own_sd=float(y.std()), peer_group=group, peer_count=len(peer_rows),
                           months=int(both.sum()))

    beta = float(((x - x.mean()) * (y - y.mean())).mean() / var_x)
    factor_sd = float(x.std())
    amplitude = abs(beta) * factor_sd

    return Cyclicality(
        ticker=ticker,
        verdict=CYCLICAL if amplitude >= AMPLITUDE_MIN else NON_CYCLICAL,
        amplitude=amplitude, beta=beta, factor_sd=factor_sd, own_sd=float(y.std()),
        peer_group=group, peer_count=len(peer_rows), months=int(both.sum()),
    )


# --- Cycle position rubric (PLAN_CYCLE_AWARENESS.md Phase 3) ---------------------------------
#
# Thresholds calibrated 2026-08-18 against the labelled sample and the full universe; the dry
# run is scripts/cycle_position_calibration.py. Fire rates among CYCLICAL names: peak 17.3%,
# trough 22.5%, both-sides clashes 0.
#
# The peak side needs 2 of 5 conditions and the trough side 3 of 5. The asymmetry is measured,
# not arbitrary: trough conditions are individually far more prevalent, because cycles are
# correlated and cyclicals are depressed together — 37% of cyclicals are loss-making right now
# and 26% carry margins 5pp below their own median. At 2-of-5 the trough side fires on 43-46%
# however tightly the individual thresholds are set, so the count is the only effective lever.
# Economically it also reads correctly: at a trough, being depressed is necessary but not
# sufficient, and needs corroboration to separate a cycle from a decline.

PEAK = "PEAK"
TROUGH = "TROUGH"
MID = "MID"
NOT_CYCLICAL_POSITION = "NOT_CYCLICAL"

_PEAK_NEAR_MAX = 0.95        # current EPS at or above this share of the 5yr max
_PEAK_FWD_DECLINE = -0.05    # forward EPS at least this far below TTM
_PEAK_ACCEL_GAP = 0.30       # 1yr earnings growth exceeding 3yr CAGR by this much
_PEAK_PE_DISCOUNT = 0.25     # current P/E this far below its own 5yr median
_PEAK_MARGIN_GAP = 0.03      # operating margin this far above its 5yr median
_PEAK_MIN_CONDITIONS = 2

_TROUGH_BELOW_MID = 0.50     # current EPS at or below this share of mid-cycle
_TROUGH_RECOVERY = 0.40      # forward EPS this far above TTM
_TROUGH_MARGIN_VS_REV = 0.20 # earnings growth trailing revenue growth by this much
_TROUGH_PE_PREMIUM = 0.40    # current P/E this far above its own 5yr median
_TROUGH_MARGIN_GAP = 0.05    # operating margin this far below its 5yr median
_TROUGH_MIN_CONDITIONS = 3


@dataclasses.dataclass
class CyclePosition:
    position: str
    peak_met: list[str] = dataclasses.field(default_factory=list)
    trough_met: list[str] = dataclasses.field(default_factory=list)
    peak_unmet: list[str] = dataclasses.field(default_factory=list)
    trough_unmet: list[str] = dataclasses.field(default_factory=list)
    notes: list[str] = dataclasses.field(default_factory=list)


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:+.1f}%"


def evaluate_cycle_position(
    verdict: str, *, ttm_eps, fwd_eps, earn_growth_1yr, earn_cagr_3yr, operating_margin,
    operating_margin_median, pe, pe_median, rev_growth_1yr, eps_max, eps_midcycle,
) -> CyclePosition:
    """Score the peak and trough rubrics. Only CYCLICAL companies get a position.

    Each condition is evaluated here rather than left to the model: the thresholds are only
    meaningful if applied the same way they were calibrated, and the measured fire rate is a
    claim about this code, not about an LLM's arithmetic.
    """
    if verdict != CYCLICAL:
        return CyclePosition(NOT_CYCLICAL_POSITION)

    loss_making = ttm_eps is not None and ttm_eps <= 0
    peak, trough = {}, {}

    # --- peak side ---
    peak[f"current EPS >= {_PEAK_NEAR_MAX:.0%} of 5yr max (earnings near a cyclical peak)"] = (
        ttm_eps is not None and eps_max is not None and eps_max > 0 and ttm_eps > 0
        and ttm_eps >= _PEAK_NEAR_MAX * eps_max)
    peak[f"forward EPS >{abs(_PEAK_FWD_DECLINE):.0%} below TTM (analysts forecast decline)"] = (
        ttm_eps is not None and fwd_eps is not None and ttm_eps > 0
        and fwd_eps / ttm_eps - 1 <= _PEAK_FWD_DECLINE)
    peak[f"1yr earnings growth exceeds 3yr CAGR by >{_PEAK_ACCEL_GAP * 100:.0f}pp (acceleration not sustained)"] = (
        earn_growth_1yr is not None and earn_cagr_3yr is not None and earn_growth_1yr > 0
        and earn_growth_1yr - earn_cagr_3yr >= _PEAK_ACCEL_GAP)
    # Repaired condition. The original compared current P/E to normalized_pe_5y
    # (price / 5yr-average EPS), which is mechanically below current P/E for any company whose
    # EPS is rising — it fired with condition 1 on 99.7% of cases and carried no information.
    # Its own rolling 5yr median P/E has no such mechanical link to EPS growth; redundancy with
    # condition 1 measured at 26.6% after the repair.
    peak[f"current P/E >{_PEAK_PE_DISCOUNT:.0%} below its own 5yr median (optically cheap on peak earnings)"] = (
        pe is not None and pe > 0 and pe_median is not None and pe_median > 0
        and pe <= pe_median * (1 - _PEAK_PE_DISCOUNT))
    peak[f"operating margin >{_PEAK_MARGIN_GAP * 100:.0f}pp above its 5yr median (margin at a cyclical high)"] = (
        operating_margin is not None and operating_margin_median is not None
        and operating_margin - operating_margin_median >= _PEAK_MARGIN_GAP)

    # --- trough side ---
    trough[f"currently loss-making, or EPS <= {_TROUGH_BELOW_MID:.0%} of mid-cycle (earnings depressed)"] = (
        loss_making or (ttm_eps is not None and eps_midcycle is not None and eps_midcycle > 0
                        and ttm_eps <= _TROUGH_BELOW_MID * eps_midcycle))
    # Sign-safe, and deliberately demanding. Analysts forecast some improvement for ~74% of
    # cyclicals, so "any improvement" is as degenerate as the pre-repair peak condition 4.
    # A loss-maker must be forecast to return to profit, not merely to lose less.
    if ttm_eps is None or fwd_eps is None:
        recovery = False
    elif loss_making:
        recovery = fwd_eps > 0
    else:
        recovery = fwd_eps / ttm_eps - 1 >= _TROUGH_RECOVERY
    trough["forward EPS forecasts a real recovery (return to profit, or "
           f">{_TROUGH_RECOVERY:.0%} above TTM)"] = recovery
    trough[f"earnings growth trailing revenue growth by >{_TROUGH_MARGIN_VS_REV * 100:.0f}pp "
           "(margin compression, not demand collapse)"] = (
        earn_growth_1yr is not None and rev_growth_1yr is not None and earn_growth_1yr < 0
        and earn_growth_1yr - rev_growth_1yr <= -_TROUGH_MARGIN_VS_REV)
    # Note this is NOT mirrored as "P/E undefined on a loss". That clause is automatically true
    # for every loss-maker, which already satisfies the depressed-earnings condition above, and
    # the pair then reproduced exactly the cond1/cond4 degeneracy this phase exists to repair
    # (co-firing on 45.8% of cyclicals, down to 8.7% once the clause was removed).
    trough[f"current P/E >{_TROUGH_PE_PREMIUM:.0%} above its own 5yr median "
           "(multiple optically high on depressed earnings)"] = (
        pe is not None and pe > 0 and pe_median is not None and pe_median > 0
        and pe >= pe_median * (1 + _TROUGH_PE_PREMIUM))
    trough[f"operating margin >{_TROUGH_MARGIN_GAP * 100:.0f}pp below its 5yr median (margin at a cyclical low)"] = (
        operating_margin is not None and operating_margin_median is not None
        and operating_margin - operating_margin_median <= -_TROUGH_MARGIN_GAP)

    peak_met = [k for k, v in peak.items() if v]
    trough_met = [k for k, v in trough.items() if v]
    is_peak = len(peak_met) >= _PEAK_MIN_CONDITIONS
    is_trough = len(trough_met) >= _TROUGH_MIN_CONDITIONS

    notes: list[str] = []
    if is_peak and is_trough:
        # Never observed across 813 cyclicals at these thresholds, but defined rather than left
        # to the model: contradictory evidence means there is no clean position to report, and
        # MID renders no standalone callout, so an ambiguous case cannot produce a confident
        # wrong claim.
        position = MID
        notes.append("Peak and trough conditions both cleared their thresholds — the evidence "
                     "is contradictory, so no cycle position is claimed.")
    elif is_peak:
        position = PEAK
    elif is_trough:
        position = TROUGH
    else:
        position = MID

    if ttm_eps is not None and eps_midcycle is not None and eps_midcycle <= 0:
        notes.append("Mid-cycle earnings are negative, so EPS-versus-mid-cycle tests are "
                     "meaningless for this company; position rests on the margin and revenue "
                     "conditions instead.")

    return CyclePosition(position, peak_met=peak_met, trough_met=trough_met,
                         peak_unmet=[k for k, v in peak.items() if not v],
                         trough_unmet=[k for k, v in trough.items() if not v],
                         notes=notes)


# --- Trough vs. value trap (PLAN_CYCLE_AWARENESS.md Phase 4) ---------------------------------
#
# A TROUGH verdict on its own is not an investment case: a depressed cyclical and a structurally
# impaired business look identical on the five trough conditions. Three independent questions
# separate them, and a trough must clear all three before it is framed as an opportunity.
# Measured 2026-08-18 over the 183 TROUGH names: demand intact 39.9%, industry-wide 57.4%,
# survivable 42.1%, all three 9.3%. Pairwise co-passing is 16-24%, so no test is implied by
# another (the failure mode that made the original peak rubric worthless).

OPPORTUNITY = "OPPORTUNITY"
POSSIBLE_VALUE_TRAP = "POSSIBLE_VALUE_TRAP"

_TROUGH_REV_VS_PEAK = 0.90     # TTM revenue this share of its own 5yr max = demand still there
_TROUGH_MAX_LEVERAGE = 4.0     # total debt / TTM EBITDA at trough earnings
_INDUSTRY_MARGIN_GAP = -0.01   # industry operating margin this far under its own 5yr median


@dataclasses.dataclass
class TroughQuality:
    quality: str
    demand_intact: bool | None = None
    industry_wide: bool | None = None
    survivable: bool | None = None
    revenue_vs_peak: float | None = None
    leverage: float | None = None
    industry: str | None = None
    notes: list[str] = dataclasses.field(default_factory=list)


def assess_trough_quality(ticker: str) -> TroughQuality:
    """Separate a mean-reverting cyclical trough from a structurally impaired business.

    Unknown is never treated as passing: a trough whose survivability cannot be established is
    not an opportunity, because the cost of that error is telling someone to buy a company that
    cannot fund itself to the recovery.
    """
    ticker = ticker.upper()
    if not _HIST_FUND_DB.exists() or not _AV_FIN_DB.exists():
        return TroughQuality(POSSIBLE_VALUE_TRAP, notes=["database not found"])

    conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
    try:
        _attach_av(conn)

        # 1. Demand. Is revenue itself in decline, or are only margins compressed? A cyclical
        #    margin trough keeps revenue near its highs; a melting ice cube does not. Revenue is
        #    used rather than rev_cagr_5yr, whose 5-year window starts in the depressed 2021 base
        #    and so reads positive for 93% of troughs — no discriminating power.
        rev = conn.execute("""
            SELECT max(ttm_revenue), arg_max(ttm_revenue, month_end_date)
            FROM monthly_pe
            WHERE ticker = ? AND ttm_revenue IS NOT NULL
              AND month_end_date >= CURRENT_DATE - INTERVAL 5 YEARS
        """, [ticker]).fetchone()

        # 2. Survivability. Computed here from the reported debt total rather than read from
        #    pe_stats.debt_to_ebitda, which is wrong: _get_ev_debt_cash in historic_fundamentals/
        #    pe.py sums long_term_debt_noncurrent + short_term_debt + current_long_term_debt, and
        #    long_term_debt_noncurrent is NULL in 100% of quarterly rows, so the column carries
        #    only the current portion of debt and understates leverage by a median of 6.1x
        #    (AT&T reads 0.25x against a true 3.24x).
        lev = conn.execute("""
            WITH d AS (
                SELECT arg_max(short_long_term_debt_total, fiscal_date_ending) AS debt
                FROM av.balance_sheets
                WHERE ticker = ? AND period_type = 'quarterly'
                  AND short_long_term_debt_total IS NOT NULL
            ), e AS (
                SELECT sum(ebitda) AS ttm FROM (
                    SELECT ebitda FROM av.income_statements
                    WHERE ticker = ? AND period_type = 'quarterly' AND ebitda IS NOT NULL
                    ORDER BY fiscal_date_ending DESC LIMIT 4
                )
            )
            SELECT CASE WHEN e.ttm > 0 THEN d.debt / e.ttm END FROM d, e
        """, [ticker, ticker]).fetchone()

        # 3. Peer breadth. An industry-wide margin squeeze points to a cycle; a company alone in
        #    its trough points to share loss or secular decline. This is what finally wires
        #    sector_stats into the equity researcher.
        industry = conn.execute(
            "SELECT industry FROM av.company_overview WHERE ticker = ?", [ticker]).fetchone()
        industry = industry[0] if industry else None
        ind = conn.execute("""
            SELECT operating_margin_median, earn_growth_1yr_median, month_end_date
            FROM sector_stats
            WHERE group_type = 'industry' AND UPPER(group_name) = UPPER(?)
              AND month_end_date >= CURRENT_DATE - INTERVAL 5 YEARS
            ORDER BY month_end_date
        """, [industry or ""]).fetchall()
    finally:
        conn.close()

    notes: list[str] = []

    revenue_vs_peak = None
    demand_intact = None
    if rev and rev[0] and rev[0] > 0 and rev[1] is not None:
        revenue_vs_peak = rev[1] / rev[0]
        demand_intact = revenue_vs_peak >= _TROUGH_REV_VS_PEAK

    leverage = lev[0] if lev and lev[0] is not None else None
    survivable = None if leverage is None else (0 <= leverage <= _TROUGH_MAX_LEVERAGE)
    if leverage is None:
        notes.append("No usable debt or EBITDA figure, so survivability could not be established.")

    industry_wide = None
    margins = [r[0] for r in ind if r[0] is not None]
    if len(margins) >= 24:
        current_margin, current_growth = ind[-1][0], ind[-1][1]
        signals = []
        if current_margin is not None:
            median_margin = float(np.median(margins))
            signals.append(current_margin - median_margin <= _INDUSTRY_MARGIN_GAP)
        if current_growth is not None:
            signals.append(current_growth < 0)
        if signals:
            industry_wide = any(signals)
    elif industry:
        notes.append(f"Too little {industry} history to judge whether the trough is industry-wide.")

    cleared = [demand_intact, industry_wide, survivable]
    quality = OPPORTUNITY if all(c is True for c in cleared) else POSSIBLE_VALUE_TRAP
    if quality == POSSIBLE_VALUE_TRAP:
        failed = []
        if demand_intact is not True:
            failed.append("revenue is below its own recent peak, so demand — not just margin — "
                          "may be impaired")
        if industry_wide is not True:
            failed.append("the industry is not depressed alongside it, pointing to a "
                          "company-specific problem rather than a cycle")
        if survivable is not True:
            failed.append("leverage at trough earnings is too high to fund the company through "
                          "a recovery")
        notes.extend(failed)

    return TroughQuality(quality, demand_intact=demand_intact, industry_wide=industry_wide,
                         survivable=survivable, revenue_vs_peak=revenue_vs_peak,
                         leverage=leverage, industry=industry, notes=notes)
