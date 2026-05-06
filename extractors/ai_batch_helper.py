"""
AI Batch Helper - Shared batch AI resolution for all statement extractors

Replaces the O(fields x concepts) per-concept AI loop with:
1. A DB lookup of prior discoveries (free, instant)
2. A single batch AI call that classifies all unmapped concepts at once

Discovered concepts are persisted to ai_discovery_queue only (no file writes).
"""

import pandas as pd
from typing import Optional, Dict

from xbrl_concept_mapper import batch_classify_concepts, StatementType


async def batch_ai_resolve_unfound_fields(
    statement_df: pd.DataFrame,
    mapping_dict: dict,
    unfound_fields: list,
    year_column: str,
    statement_type: StatementType,
    ticker: str,
    mapping_manager=None,
    filing_date=None,
    period_end_date=None,
) -> Dict[str, tuple]:
    """
    Resolve unfound fields using DB discovery lookup + batch AI classification.

    Phase A: Check DB for prior AI discoveries (free)
    Phase B: Batch classify remaining unmapped concepts via Claude Haiku

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

    # Only consider concepts that have a numeric value for this period.
    if year_column in main_items.columns:
        available_concepts = main_items.loc[
            main_items[year_column].notna(), 'concept'
        ].unique().tolist()
    else:
        available_concepts = main_items['concept'].unique().tolist()

    # Strip namespace prefix (e.g. us-gaap_, dei_, tsla_) for matching
    concept_name_map = {}  # clean_name -> full_concept
    for c in available_concepts:
        clean = c.split('_', 1)[1] if '_' in c else c
        concept_name_map[clean] = c

    # Unmapped = present in XBRL statement but not in any static mapping entry.
    # Strip namespace prefix from mapping entries to match the same bare names used in concept_name_map.
    all_mapped_concepts: set = set()
    for mapped_concepts in mapping_dict.values():
        for c in mapped_concepts:
            all_mapped_concepts.add(c.split('_', 1)[1] if '_' in c else c)

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
    # Phase A: DB discovery lookup (free, no API call)
    # ================================================================
    if mapping_manager is not None:
        try:
            prior = mapping_manager.get_prior_discoveries(statement_type)

            for concept_name, field_name in prior.items():
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
    concepts_to_classify = [
        c for c in unmapped_concepts
        if c not in concepts_resolved_by_db
    ]

    if not concepts_to_classify:
        print(f"  No remaining concepts to batch classify")
        return resolved

    print(f"  Phase B: batch classifying {len(concepts_to_classify)} concepts...")

    ai_results = {}
    api_failed = False
    try:
        ai_results = await batch_classify_concepts(concepts_to_classify, statement_type)
    except Exception as e:
        print(f"  Phase B: batch classification failed ({e})")
        api_failed = True

    # Log API failures — every concept we tried but couldn't classify due to the error
    if api_failed and mapping_manager is not None:
        for concept_name in concepts_to_classify:
            mapping_manager.log_missed_concept(
                ticker=ticker,
                statement_type=statement_type,
                reason='api_failure',
                filing_date=filing_date,
                period_end_date=period_end_date,
                concept=concept_name,
            )
        return resolved

    # Match AI results to unfound fields and extract values
    classified_concepts = set()
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
                classified_concepts.add(concept_name)
                print(f"  AI batch: {concept_name} -> {field_name}")

    phase_b_count = len(resolved) - len(concepts_resolved_by_db)
    if phase_b_count > 0:
        print(f"  Phase B: resolved {phase_b_count} additional fields via batch AI")

    # Log concepts that AI could not classify (no_match)
    if mapping_manager is not None:
        no_match_concepts = [
            c for c in concepts_to_classify
            if c not in classified_concepts and c not in concepts_resolved_by_db
        ]
        for concept_name in no_match_concepts:
            mapping_manager.log_missed_concept(
                ticker=ticker,
                statement_type=statement_type,
                reason='no_match',
                filing_date=filing_date,
                period_end_date=period_end_date,
                concept=concept_name,
            )

    return resolved
