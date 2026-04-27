"""
AI Batch Helper - Shared batch AI resolution for all statement extractors

Replaces the O(fields x concepts) per-concept AI loop with:
1. A DB lookup of prior discoveries (free, instant)
2. A single batch AI call that classifies all unmapped concepts at once
"""

import pandas as pd
from typing import Optional, Dict, Set

from xbrl_concept_mapper import batch_classify_concepts, StatementType


async def batch_ai_resolve_unfound_fields(
    statement_df: pd.DataFrame,
    mapping_dict: dict,
    unfound_fields: list,
    year_column: str,
    statement_type: StatementType,
    ticker: str,
    mapping_manager=None
) -> Dict[str, tuple]:
    """
    Resolve unfound fields using DB discovery lookup + batch AI classification.

    Phase A: Check DB for prior AI discoveries
    Phase B: Batch classify remaining unmapped concepts via Ollama

    Args:
        statement_df: The XBRL statement DataFrame
        mapping_dict: The static mapping dict (e.g., INCOME_STATEMENT_MAPPING)
        unfound_fields: List of field names that Pass 1 couldn't resolve
        year_column: Date column to extract values from
        statement_type: 'income', 'balance', or 'cashflow'
        ticker: Company ticker symbol
        mapping_manager: Optional XBRLMappingManager instance for DB lookups

    Returns:
        Dict of {field_name: (value, "concept (AI-discovered)")} for resolved fields
    """
    if not unfound_fields:
        return {}

    # Filter to main items (no dimensional breakdowns)
    main_items = statement_df[
        (statement_df['dimension'] == False) &
        (statement_df['abstract'] == False)
    ]

    # Get concepts that actually have a numeric value in the target period.
    # Concepts present in the statement but with NaN for this period would
    # never yield a value, so there is no point classifying them with AI.
    if year_column in main_items.columns:
        available_concepts = main_items.loc[
            main_items[year_column].notna(), 'concept'
        ].unique().tolist()
    else:
        available_concepts = main_items['concept'].unique().tolist()

    # Strip namespace prefix (e.g. us-gaap_, dei_, apo_) for mapping
    concept_name_map = {}  # clean_name -> full_concept
    for c in available_concepts:
        clean = c.split('_', 1)[1] if '_' in c else c
        concept_name_map[clean] = c

    # Get all concepts already in the static mapping file
    all_mapped_concepts = set()
    for mapped_concepts in mapping_dict.values():
        all_mapped_concepts.update(mapped_concepts)

    # Unmapped concepts = available in statement but not in any static mapping
    unmapped_concepts = [
        name for name in concept_name_map.keys()
        if name not in all_mapped_concepts
    ]

    if not unmapped_concepts:
        print(f"  No unmapped concepts available for AI resolution")
        return {}

    print(f"  Pass 2: {len(unfound_fields)} unfound fields, {len(unmapped_concepts)} unmapped concepts")

    resolved = {}
    remaining_unfound = set(unfound_fields)
    concepts_resolved_by_db = set()

    # ================================================================
    # Phase A: DB discovery lookup
    # ================================================================
    if mapping_manager is not None:
        try:
            prior = mapping_manager.get_prior_discoveries(statement_type)

            for concept_name, field_name in prior.items():
                if field_name not in remaining_unfound:
                    continue
                if concept_name not in concept_name_map:
                    continue

                # Try to extract value
                full_concept = concept_name_map[concept_name]
                rows = main_items[main_items['concept'] == full_concept]

                if not rows.empty and year_column in rows.columns:
                    value = rows.iloc[0][year_column]
                    if pd.notna(value):
                        resolved[field_name] = (float(value), f"{concept_name} (AI-discovered)")
                        remaining_unfound.discard(field_name)
                        concepts_resolved_by_db.add(concept_name)
                        print(f"  DB hit: {concept_name} -> {field_name}")

            if concepts_resolved_by_db:
                print(f"  Phase A: resolved {len(concepts_resolved_by_db)} fields from prior discoveries")
        except Exception as e:
            print(f"  Phase A: DB lookup failed ({e}), continuing to Phase B")

    if not remaining_unfound:
        return resolved

    # ================================================================
    # Phase B: Batch AI classification
    # ================================================================
    # Only classify concepts not already resolved by DB
    concepts_to_classify = [
        c for c in unmapped_concepts
        if c not in concepts_resolved_by_db
    ]

    if not concepts_to_classify:
        print(f"  No remaining concepts to batch classify")
        return resolved

    print(f"  Phase B: batch classifying {len(concepts_to_classify)} concepts...")

    try:
        ai_results = await batch_classify_concepts(
            concepts_to_classify,
            statement_type
        )
    except Exception as e:
        print(f"  Phase B: batch classification failed ({e})")
        return resolved

    # Match AI results to unfound fields and extract values
    for concept_name, field_name in ai_results.items():
        if field_name not in remaining_unfound:
            continue
        if concept_name not in concept_name_map:
            continue

        full_concept = concept_name_map[concept_name]
        rows = main_items[main_items['concept'] == full_concept]

        if not rows.empty and year_column in rows.columns:
            value = rows.iloc[0][year_column]
            if pd.notna(value):
                resolved[field_name] = (float(value), f"{concept_name} (AI-discovered)")
                remaining_unfound.discard(field_name)
                print(f"  AI batch: {concept_name} -> {field_name}")

    phase_b_count = len(resolved) - len(concepts_resolved_by_db)
    if phase_b_count > 0:
        print(f"  Phase B: resolved {phase_b_count} additional fields via batch AI")

    return resolved
