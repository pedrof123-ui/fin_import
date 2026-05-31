"""
Tests for Phase 3 — industry override infrastructure (PLAN.md).

Covers:
  - sic_lookup: SIC → FF48 conversion
  - industry_overrides: data structure and get_industry_concepts()
  - _extract_value: industry concepts prepended correctly
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# SIC lookup
# ---------------------------------------------------------------------------

class TestSicLookup:

    def test_known_bank_sic(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(6020) == "Banks"

    def test_known_software_sic(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(7372) == "BusSv"

    def test_known_pharma_sic(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(2836) == "Drugs"

    def test_known_insurance_sic(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(6311) == "Insur"

    def test_known_reit_sic(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(6500) == "RlEst"

    def test_known_oil_sic(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(1311) == "Oil"

    def test_unknown_sic_returns_none(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(9999) is None

    def test_none_input_returns_none(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48(None) is None

    def test_string_sic_input(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48("6020") == "Banks"

    def test_invalid_string_returns_none(self):
        from xbrl_mappings.sic_lookup import get_ff48
        assert get_ff48("not_a_number") is None


# ---------------------------------------------------------------------------
# Industry overrides module
# ---------------------------------------------------------------------------

class TestIndustryOverrides:

    def test_module_loads(self):
        from xbrl_mappings.industry_overrides import INDUSTRY_OVERRIDES, get_industry_concepts
        assert isinstance(INDUSTRY_OVERRIDES, dict)
        assert set(INDUSTRY_OVERRIDES.keys()) >= {"income", "balance", "cashflow"}

    def test_all_three_statements_present(self):
        from xbrl_mappings.industry_overrides import INDUSTRY_OVERRIDES
        for stmt in ("income", "balance", "cashflow"):
            assert stmt in INDUSTRY_OVERRIDES, f"'{stmt}' missing from INDUSTRY_OVERRIDES"

    def test_fin_has_revenue_override(self):
        from xbrl_mappings.industry_overrides import get_industry_concepts
        concepts = get_industry_concepts("income", "Fin", "revenue")
        assert len(concepts) > 0, "Expected bank revenue concepts for Fin"

    def test_fin_has_long_term_debt_override(self):
        from xbrl_mappings.industry_overrides import get_industry_concepts
        concepts = get_industry_concepts("balance", "Fin", "long_term_debt")
        assert len(concepts) > 0, "Expected debt concepts for Fin balance sheet"

    def test_insur_has_cost_of_revenue_override(self):
        from xbrl_mappings.industry_overrides import get_industry_concepts
        concepts = get_industry_concepts("income", "Insur", "cost_of_revenue")
        assert len(concepts) > 0, "Expected insurance claims concepts for Insur income"

    def test_none_ff48_returns_empty(self):
        from xbrl_mappings.industry_overrides import get_industry_concepts
        assert get_industry_concepts("income", None, "revenue") == []

    def test_empty_ff48_returns_empty(self):
        from xbrl_mappings.industry_overrides import get_industry_concepts
        assert get_industry_concepts("income", "", "revenue") == []

    def test_unknown_ff48_returns_empty(self):
        from xbrl_mappings.industry_overrides import get_industry_concepts
        assert get_industry_concepts("income", "XXXXUNKNOWN", "revenue") == []

    def test_unknown_field_returns_empty(self):
        from xbrl_mappings.industry_overrides import get_industry_concepts
        assert get_industry_concepts("income", "Fin", "nonexistent_field_xyz") == []

    def test_no_field_has_empty_concept_list(self):
        from xbrl_mappings.industry_overrides import INDUSTRY_OVERRIDES
        errors = []
        for stmt, by_ff48 in INDUSTRY_OVERRIDES.items():
            for ff48, by_field in by_ff48.items():
                for field, concepts in by_field.items():
                    if not concepts:
                        errors.append(f"{stmt}/{ff48}/{field} has empty concept list")
        assert not errors, "\n".join(errors[:10])

    def test_all_concepts_are_strings(self):
        from xbrl_mappings.industry_overrides import INDUSTRY_OVERRIDES
        errors = []
        for stmt, by_ff48 in INDUSTRY_OVERRIDES.items():
            for ff48, by_field in by_ff48.items():
                for field, concepts in by_field.items():
                    for c in concepts:
                        if not isinstance(c, str) or not c.strip():
                            errors.append(f"{stmt}/{ff48}/{field}: bad concept {c!r}")
        assert not errors, "\n".join(errors[:10])

    def test_no_namespace_prefix_in_concepts(self):
        """All concepts should be bare names (no us-gaap_ prefix, no IFRS colon)."""
        from xbrl_mappings.industry_overrides import INDUSTRY_OVERRIDES
        errors = []
        for stmt, by_ff48 in INDUSTRY_OVERRIDES.items():
            for ff48, by_field in by_ff48.items():
                for field, concepts in by_field.items():
                    for c in concepts:
                        if c.startswith("us-gaap_") or ":" in c:
                            errors.append(f"{stmt}/{ff48}/{field}: '{c}' has namespace prefix")
        assert not errors, "\n".join(errors[:10])

    def test_all_fields_are_valid_field_names(self):
        from xbrl_mappings.industry_overrides import INDUSTRY_OVERRIDES
        from xbrl_mappings import INCOME_STATEMENT_MAPPING, BALANCE_SHEET_MAPPING, CASH_FLOW_MAPPING
        valid = {
            "income": set(INCOME_STATEMENT_MAPPING),
            "balance": set(BALANCE_SHEET_MAPPING),
            "cashflow": set(CASH_FLOW_MAPPING),
        }
        errors = []
        for stmt, by_ff48 in INDUSTRY_OVERRIDES.items():
            for ff48, by_field in by_ff48.items():
                for field in by_field:
                    if field not in valid.get(stmt, set()):
                        errors.append(f"{stmt}/{ff48}: '{field}' is not a valid field_name")
        assert not errors, "\n".join(errors[:10])


# ---------------------------------------------------------------------------
# _extract_value with industry override
# ---------------------------------------------------------------------------

def _make_stmt_df(concepts_and_values: list[tuple[str, float]]) -> pd.DataFrame:
    """Build a minimal statement DataFrame for testing _extract_value."""
    rows = []
    for concept, value in concepts_and_values:
        rows.append({
            "concept": concept,
            "dimension": False,
            "abstract": False,
            "2024-12-31": value,
        })
    return pd.DataFrame(rows)


class TestExtractValueIndustryOverride:

    def test_industry_concept_found_before_generic(self):
        """When ff48_code is set, industry concepts are tried before generic ones."""
        from extractors.statement_extractor import _extract_value
        from xbrl_mappings.industry_overrides import get_industry_concepts

        # Find a field and ff48 that actually has overrides
        fin_revenue = get_industry_concepts("income", "Fin", "revenue")
        if not fin_revenue:
            pytest.skip("No Fin/income/revenue override — update test corpus")

        industry_concept = fin_revenue[0]
        generic_concept = "Revenues"  # always in generic income mapping

        # DataFrame contains ONLY the industry concept (no generic Revenues)
        stmt_df = _make_stmt_df([(f"us-gaap_{industry_concept}", 999_000_000.0)])

        from xbrl_mappings import INCOME_STATEMENT_MAPPING
        value, concept_used = _extract_value(
            stmt_df, "revenue", "2024-12-31",
            INCOME_STATEMENT_MAPPING, set(), frozenset(),
            ff48_code="Fin", statement_type="income",
        )
        assert value == 999_000_000.0
        assert industry_concept in concept_used

    def test_falls_back_to_generic_when_no_industry_match(self):
        """When industry concepts yield no hit, generic mapping still works."""
        from extractors.statement_extractor import _extract_value
        from xbrl_mappings import INCOME_STATEMENT_MAPPING

        stmt_df = _make_stmt_df([("us-gaap_Revenues", 500_000_000.0)])

        value, concept_used = _extract_value(
            stmt_df, "revenue", "2024-12-31",
            INCOME_STATEMENT_MAPPING, set(), frozenset(),
            ff48_code="Fin", statement_type="income",
        )
        assert value == 500_000_000.0

    def test_no_ff48_behavior_unchanged(self):
        """Without ff48_code, behavior is identical to the pre-Phase-3 baseline."""
        from extractors.statement_extractor import _extract_value
        from xbrl_mappings import INCOME_STATEMENT_MAPPING

        stmt_df = _make_stmt_df([("us-gaap_Revenues", 100.0)])

        value_with, _ = _extract_value(
            stmt_df, "revenue", "2024-12-31",
            INCOME_STATEMENT_MAPPING, set(), frozenset(),
            ff48_code=None, statement_type=None,
        )
        value_without, _ = _extract_value(
            stmt_df, "revenue", "2024-12-31",
            INCOME_STATEMENT_MAPPING, set(), frozenset(),
        )
        assert value_with == value_without == 100.0

    def test_no_double_count_when_industry_concept_also_in_generic(self):
        """
        If an industry concept is also in the generic list, it must not be counted twice
        for aggregation fields. The deduplication in _extract_value prevents this.
        """
        from extractors.statement_extractor import _extract_value
        from xbrl_mappings import INCOME_STATEMENT_MAPPING

        # selling_general_admin is an aggregation field — all matching concepts are summed
        # Use a concept that exists in the generic mapping
        stmt_df = _make_stmt_df([
            ("us-gaap_SellingGeneralAndAdministrativeExpense", 50_000_000.0),
        ])

        value, _ = _extract_value(
            stmt_df, "selling_general_admin", "2024-12-31",
            INCOME_STATEMENT_MAPPING,
            aggregation_fields={"selling_general_admin"},
            ff48_code="Aero", statement_type="income",
        )
        # Must be exactly 50M, not 100M (which would happen if the concept was counted twice)
        assert value == 50_000_000.0
