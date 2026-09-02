"""
PLAN_DEBT_MATURITY.md Phase 1 — extraction + parsing.

Given a ticker, fetches the latest 10-K, pulls the two target XBRL debt-note
concepts, and parses them generically into debt_tranches rows:

  - us-gaap:ScheduleOfDebtInstrumentsTextBlock -> per-tranche coupon+maturity+amount
  - us-gaap:ScheduleOfMaturitiesOfLongTermDebtTableTextBlock -> aggregate principal-by-year
    ladder (no coupon -- that table never carries a rate, by definition)

Neither concept is guaranteed present (see docs/debt_maturity_coverage.md: ~1/3 of tickers
have neither). A ticker with no coverage returns an empty list -- that is the expected,
normal case, not an error.

These tables are HTML rendered from XBRL facts, and pandas.read_html turns each colspan
into duplicate adjacent cells (e.g. a 3-column-wide "3.7%" label becomes three "3.7%"
cells). After collapsing those duplicates, every row we care about reduces to the same
shape: [description/coupon tokens...] [year or "Thereafter" token] [amount tokens...] --
regardless of whether it's IBM's per-bond-year table or Apple's two-bucket summary. So
parsing works off that generic shape (a standalone 4-digit-year token as the pivot, then
the first parseable number after it), not any one filer's column layout, per CLAUDE.md
rule 6. A two-year comparative table (current FY balance next to prior FY) is handled by
taking the *first* amount after the pivot, since EDGAR renders the current period first.
"""

import re
from io import StringIO
from typing import Optional

import pandas as pd
from edgar import Company

DEBT_INSTRUMENTS_CONCEPT = "us-gaap:ScheduleOfDebtInstrumentsTextBlock"
MATURITIES_CONCEPT = "us-gaap:ScheduleOfMaturitiesOfLongTermDebtTableTextBlock"

_COUPON_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# Restricted to a plausible fiscal-year range (19xx/20xx/21xx) so a coincidentally
# 4-digit dollar amount in an adjacent column can't be mistaken for a year token.
# The optional ".0" tolerates a year column pandas rendered as float (mixed dtype
# from a NaN elsewhere in the column).
_YEAR = r"(?:19|20|21)\d{2}"
_YEAR_TOKEN_RE = re.compile(rf"^({_YEAR})(?:\.0)?(?:\s*[–—-]\s*({_YEAR})(?:\.0)?)?$")
_THEREAFTER_TOKEN_RE = re.compile(r"^thereafter$", re.IGNORECASE)
_TOTAL_RE = re.compile(r"^total\b", re.IGNORECASE)
# Fallback for filers that don't break the year into its own table column -- a single
# flat cell like "3.45% Notes due 2028". Requires "due"/"matur*" near the year so it
# doesn't grab an unrelated "as of December 2025" date elsewhere in the description.
_DUE_YEAR_RE = re.compile(rf"(?:due|matur\w*)\D{{0,15}}?({_YEAR})", re.IGNORECASE)

# Currency cues, checked against both section-header rows (e.g. "Euro debt (weighted...")
# and individual tranche descriptions (e.g. "Pound sterling (4.9%)").
_CURRENCY_KEYWORDS = {
    "USD": ("u.s. dollar", "usd"),
    "EUR": ("euro", "eur", "€"),
    "GBP": ("pound sterling", "gbp", "£"),
    "JPY": ("japanese yen", "yen", "jpy", "¥"),
    "CHF": ("swiss franc", "chf"),
    "CNY": ("renminbi", "rmb", "cny"),
}


def _clean_amount(val) -> Optional[float]:
    """Parse a table cell as a dollar amount. An em-dash/hyphen placeholder is a
    disclosed zero (e.g. a tranche that fully matured before fiscal year end), not
    missing data, so it parses to 0.0 rather than None."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").strip()
    if s in ("-", "–", "—"):
        return 0.0
    if not re.match(r"^-?\d+(\.\d+)?$", s):
        return None
    n = float(s)
    return -n if neg else n


def _meaningful_tokens(row: pd.Series) -> list[str]:
    """Row cells with blanks/currency-symbol filler dropped and colspan-duplicated
    consecutive cells collapsed to one."""
    tokens = []
    prev = None
    for val in row:
        if pd.isna(val):
            continue
        s = str(val).strip()
        if not s or s in ("$", "nan"):
            continue
        if s == prev:
            continue
        tokens.append(s)
        prev = s
    return tokens


def _find_boundary(tokens: list[str]) -> tuple[Optional[int], Optional[int]]:
    """Locate the standalone year/range/"Thereafter" token that separates the
    description (coupon, currency, tranche name) from the value columns."""
    for i, tok in enumerate(tokens):
        if _THEREAFTER_TOKEN_RE.match(tok):
            return i, None
        m = _YEAR_TOKEN_RE.match(tok)
        if m:
            y1 = int(m.group(1))
            y2 = int(m.group(2)) if m.group(2) else y1
            return i, round((y1 + y2) / 2)
    return None, None


def _detect_currency(text: str) -> Optional[str]:
    t = text.lower()
    for code, keywords in _CURRENCY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return code
    return None


def _parse_table_rows(html: str, require_coupon: bool) -> list[dict]:
    try:
        tables = pd.read_html(StringIO(html))
    except Exception:
        return []

    rows = []
    for table in tables:
        current_currency = "USD"
        for _, row in table.iterrows():
            tokens = _meaningful_tokens(row)
            if not tokens or _TOTAL_RE.match(tokens[0]):
                continue

            boundary_idx, maturity_year = _find_boundary(tokens)
            if boundary_idx is None:
                # Fallback for a flat single-cell description ("3.45% Notes due 2028")
                # that never splits the year into its own column.
                joined = " ".join(tokens)
                m = _DUE_YEAR_RE.search(joined) if "%" in joined else None
                if m:
                    boundary_idx, maturity_year = 0, int(m.group(1))
                else:
                    # No pivot at all -- either a subtotal (pure numbers, e.g. a currency
                    # section's running total -- leaves the section's currency in effect)
                    # or a section-header label (real text, e.g. "Euro debt..." or the
                    # ambiguous "Other currencies..." -- updates it, resetting to USD when
                    # the header doesn't name a specific currency, so an unresolved
                    # umbrella section can't leak the *previous* section's currency onto
                    # later rows).
                    if any(_clean_amount(t) is None for t in tokens):
                        current_currency = _detect_currency(joined) or "USD"
                    continue

            label = " ".join(tokens[:boundary_idx]) if boundary_idx else tokens[0]
            # Coupon position relative to the year varies by filer (IBM: coupon then
            # year; Southern Co: description, year, *then* coupon; Apple: coupon range
            # inside the description). Take the first token anywhere in the row that
            # carries a "%" -- amount columns never do -- and stop there so a second
            # "effective rate" comparison column later in the row (Apple) isn't averaged in.
            coupon_token = next((t for t in tokens if "%" in t), None)
            coupons = _COUPON_RE.findall(coupon_token) if coupon_token else []
            if require_coupon and not coupons:
                continue
            coupon_rate = (
                sum(float(c) for c in coupons) / len(coupons) / 100 if coupons else None
            )

            amount = None
            for tok in tokens[boundary_idx + 1:]:
                amount = _clean_amount(tok)
                if amount is not None:
                    break
            if amount is None:
                continue

            rows.append({
                "coupon_rate": coupon_rate,
                "maturity_year": maturity_year,
                "amount": amount,
                "currency": _detect_currency(label) or current_currency,
                "raw_label": label or tokens[boundary_idx],
            })
    return rows


def parse_maturities_ladder(html: str) -> list[dict]:
    """Parse a ScheduleOfMaturitiesOfLongTermDebt table into year-bucket rows.
    No coupon in this table by definition. A "Thereafter" bucket has no single
    maturity year -- stored with maturity_year=None rather than guessing one."""
    rows = _parse_table_rows(html, require_coupon=False)
    for r in rows:
        r["source_concept"] = "maturities_ladder"
    return rows


def parse_debt_instruments(html: str) -> list[dict]:
    """Parse a ScheduleOfDebtInstruments table into per-tranche rows. Rows without a
    coupon rate in their description (headers, reconciliation lines like "Less:
    unamortized discount") are skipped -- this table always states the rate."""
    rows = _parse_table_rows(html, require_coupon=True)
    for r in rows:
        r["source_concept"] = "debt_instruments"
    return rows


def extract_debt_tranches(ticker: str, filing=None) -> list[dict]:
    """Fetch (or reuse) a ticker's latest 10-K and return parsed debt_tranches rows.
    Returns [] when neither target concept is tagged -- the normal case for tickers
    without public bond-style debt disclosures."""
    if filing is None:
        filing = Company(ticker).get_filings(form="10-K", amendments=False).latest()
    if filing is None:
        return []

    xb = filing.xbrl()
    facts = xb.facts.to_dataframe()

    rows = []
    for concept, parser in (
        (DEBT_INSTRUMENTS_CONCEPT, parse_debt_instruments),
        (MATURITIES_CONCEPT, parse_maturities_ladder),
    ):
        matches = facts[facts["concept"] == concept]
        for _, f in matches.iterrows():
            html = f.get("value")
            if not isinstance(html, str) or not html.strip():
                continue
            fiscal_year = int(f["fiscal_year"]) if pd.notna(f.get("fiscal_year")) else None
            for r in parser(html):
                r["ticker"] = ticker
                r["cik"] = str(filing.cik)
                r["fiscal_year"] = fiscal_year
                r["filed_date"] = str(filing.filing_date)
                rows.append(r)
    return rows


if __name__ == "__main__":
    import argparse
    import os

    from dotenv import load_dotenv

    load_dotenv()
    from edgar import set_identity

    set_identity(os.getenv("SEC_ID"))

    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    args = p.parse_args()

    for row in extract_debt_tranches(args.ticker.upper()):
        print(row)
