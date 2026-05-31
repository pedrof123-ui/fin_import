"""
Resolve a 4-digit SIC code to a Fama-French 48 industry code.
Delegates to edgartools' sic_industry.py — no duplication.
"""
import sys
from pathlib import Path

_EDGAR_PATH = Path(__file__).parent.parent / "edgartools"
if str(_EDGAR_PATH) not in sys.path:
    sys.path.insert(0, str(_EDGAR_PATH))

from edgar.xbrl.standardization.sic_industry import sic_to_fama_french


def get_ff48(sic: int | str | None) -> str | None:
    """Return FF48 industry code for a SIC code, or None if unknown/invalid."""
    if sic is None:
        return None
    try:
        return sic_to_fama_french(int(sic))
    except Exception:
        return None
