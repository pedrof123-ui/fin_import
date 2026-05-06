"""
Shared financial statement extractor core.
Parameterized by statement type — used by income, balance, and cash flow wrappers.
"""

import asyncio
import pandas as pd
from pathlib import Path
from typing import Optional
from .filing import parse_date


def _extract_value(
    statement_df: pd.DataFrame,
    field_name: str,
    year_column: str,
    mapping: dict,
    aggregation_fields: set,
    max_fields: set = frozenset(),
) -> tuple[Optional[float], Optional[str]]:
    concepts = mapping.get(field_name)
    if concepts is None:
        return None, None

    main_items = statement_df[
        ~statement_df['dimension'] &
        ~statement_df['abstract']
    ].copy()
    main_items['bare_concept'] = main_items['concept'].apply(
        lambda c: c.split('_', 1)[1] if '_' in c else c
    )

    should_aggregate = field_name in aggregation_fields
    # For total-line fields (revenue, total_assets, etc.) take the maximum across all
    # matching concepts — a subtotal can never exceed the true total, so the largest
    # value is the most complete figure (e.g. WMT Revenues > RFCWCEA).
    should_max = field_name in max_fields
    found_values: list[float] = []
    found_concepts: list[str] = []

    for concept in concepts:
        bare = concept.split('_', 1)[1] if '_' in concept else concept
        rows = main_items[main_items['bare_concept'] == bare]
        if not rows.empty and year_column in rows.columns:
            value = rows.iloc[0][year_column]
            if pd.notna(value):
                if should_aggregate or should_max:
                    found_values.append(float(value))
                    found_concepts.append(concept)
                else:
                    return float(value), concept

    if found_values:
        if len(found_values) == 1:
            return found_values[0], found_concepts[0]
        if should_max:
            idx = found_values.index(max(found_values))
            return found_values[idx], found_concepts[idx]
        return sum(found_values), ' + '.join(found_concepts)

    return None, None


def _log_ai_discoveries(
    ai_discovered: list[dict],
    result_df: pd.DataFrame,
    statement_type: str,
    ticker: str,
    filing_date,
    most_recent_period: str,
    mapping_manager,
):
    from datetime import date as date_type
    try:
        filing_date_obj = date_type.fromisoformat(str(filing_date)) if filing_date else None
        period_date_obj = date_type.fromisoformat(str(most_recent_period)[:10]) if most_recent_period else None
        logged_count = 0
        for item in ai_discovered:
            field_row = result_df[result_df['Field'] == item['field']]
            value = field_row.iloc[0]['Value'] if not field_row.empty else None
            if value is not None:
                try:
                    mapping_manager.conn.execute("""
                        INSERT OR IGNORE INTO ai_discovery_queue
                        (ticker, statement_type, field_name, concept, value, filing_date, period_end_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [ticker, statement_type, item['field'], item['concept'], float(value),
                          filing_date_obj, period_date_obj])
                    logged_count += 1
                except Exception as e:
                    print(f"    Failed to log {item['concept']}: {e}")
        if logged_count > 0:
            print(f"  Logged {logged_count} AI discoveries to database")
    except Exception as e:
        print(f"  Failed to log to database: {e}")


async def extract_statement(
    filing,
    ticker: str,
    filing_type: str,
    mapping: dict,
    get_stmt_fn,
    alt_names: list[str],
    aggregation_fields: set,
    statement_type: str,
    label: str,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    use_ai_fallback: bool = True,
    max_fields: set = frozenset(),
    prior_period_fields: frozenset = frozenset(),
) -> pd.DataFrame:
    print(f"\n{'='*80}\nEXTRACTING {label}\n{'='*80}")

    filing_date = getattr(filing, 'filing_date', None)
    period_of_report = getattr(filing, 'report_date', None) or getattr(filing, 'period_of_report', None)
    form_type = getattr(filing, 'form', filing_type)

    is_annual = 'K' in form_type and 'Q' not in form_type
    period_type = 'Annual' if is_annual else 'Quarterly'

    if period_of_report and not year:
        period_date = parse_date(period_of_report)
        if period_date:
            year = period_date.year

    if not is_annual and period_of_report and not quarter:
        period_date = parse_date(period_of_report)
        if period_date:
            # Approximate with calendar quarter; callers should pass quarter explicitly.
            quarter = ((period_date.month - 1) // 3) + 1

    # Open one mapping manager for enrichment, Pass 2, and miss logging
    mapping_manager = None
    try:
        from xbrl_mapping_manager_multi_statement import XBRLMappingManager
        _db_path = str(Path(__file__).parent.parent / "data" / "xbrl_mappings_multi.duckdb")
        mapping_manager = XBRLMappingManager(_db_path)
    except Exception as e:
        print(f"  Warning: mapping DB unavailable ({e})")

    # Enrich static mapping with AI-discovered concepts validated across >= 2 filings
    if mapping_manager is not None:
        try:
            mapping = mapping_manager.get_enriched_mapping(statement_type, mapping)
        except Exception as e:
            print(f"  Warning: mapping enrichment failed ({e})")

    try:
        xbrl = await asyncio.to_thread(filing.xbrl)
        if xbrl is None:
            raise ValueError("Unable to extract XBRL data from filing")
    except Exception as e:
        if mapping_manager:
            mapping_manager.close()
        raise ValueError(f"Error accessing XBRL data: {e}")

    try:
        stmt = get_stmt_fn(xbrl)
        if stmt is None:
            for name in alt_names:
                try:
                    stmt = xbrl.get_statement(name)
                    if stmt is not None:
                        print(f"Found {label} using alternative name: {name}")
                        break
                except Exception:
                    continue
        if stmt is None:
            raise ValueError(f"{label} not available in XBRL data")

        stmt_df = stmt.to_dataframe(presentation=False)
        if stmt_df.empty:
            raise ValueError(f"{label} DataFrame is empty")
    except Exception as e:
        if mapping_manager:
            mapping_manager.close()
        raise ValueError(f"Error retrieving {label}: {e}")

    # edgartools appends suffixes like " (FY)", " (Q1)", " (YTD)" to duration-based
    # periods (income statement, cash flow). Instant periods (balance sheet) use plain
    # YYYY-MM-DD. Match both by requiring the first 10 chars to be a date.
    date_columns = [
        col for col in stmt_df.columns
        if isinstance(col, str) and len(col) >= 10 and col[4] == '-' and col[7] == '-'
    ]
    if not date_columns:
        if mapping_manager:
            mapping_manager.close()
        raise ValueError(f"No date columns found in {label}")

    sorted_date_columns = sorted(date_columns, key=lambda c: c[:10], reverse=True)
    most_recent_period = sorted_date_columns[0]
    prior_period = sorted_date_columns[1] if len(sorted_date_columns) >= 2 else None
    period_end_date = most_recent_period[:10]
    print(f"\nAvailable periods: {', '.join(date_columns)}")
    print(f"Using most recent period: {most_recent_period}")
    if use_ai_fallback:
        print("AI fallback enabled (batch mode)")

    print(f"\nExtracting {len(mapping)} line items...")

    results = []
    found_count = 0
    unfound_fields = []

    for field_name in mapping:
        col = prior_period if (field_name in prior_period_fields and prior_period) else most_recent_period
        value, concept_used = _extract_value(stmt_df, field_name, col, mapping, aggregation_fields, max_fields)
        if value is not None:
            found_count += 1
            results.append({'Status': 'found', 'Field': field_name, 'Value': value, 'Concept': concept_used})
        else:
            unfound_fields.append(field_name)
            results.append({'Status': 'not_found', 'Field': field_name, 'Value': None, 'Concept': 'Not Found'})

    print(f"\n  Pass 1 (static): {found_count}/{len(mapping)} fields found")

    ai_discovered: list[dict] = []
    if use_ai_fallback and unfound_fields:
        print(f"  Pass 2 (AI): resolving {len(unfound_fields)} unfound fields...")
        try:
            from extractors.ai_batch_helper import batch_ai_resolve_unfound_fields
            ai_results = await batch_ai_resolve_unfound_fields(
                statement_df=stmt_df,
                mapping_dict=mapping,
                unfound_fields=unfound_fields,
                year_column=most_recent_period,
                statement_type=statement_type,
                ticker=ticker,
                mapping_manager=mapping_manager,
                filing_date=filing_date,
                period_end_date=period_end_date,
            )
            for r in results:
                if r['Field'] in ai_results:
                    val, concept_used = ai_results[r['Field']]
                    r['Status'] = 'found'
                    r['Value'] = val
                    r['Concept'] = concept_used
                    found_count += 1
                    ai_discovered.append({
                        'field': r['Field'],
                        'concept': concept_used.replace(' (AI-discovered)', ''),
                    })
        except Exception as e:
            print(f"  Pass 2 failed: {e}")

    result_df = pd.DataFrame(results)
    result_df.insert(0, 'Ticker', ticker)
    result_df.insert(1, 'Fiscal_Year', year)
    result_df.insert(2, 'Period_End_Date', period_end_date)
    result_df.insert(3, 'Filing_Date', filing_date)
    result_df.insert(4, 'Filing_Type', form_type)
    result_df.insert(5, 'Period_Type', period_type)
    result_df.insert(6, 'Quarter', quarter if not is_annual else None)

    data_quality = found_count / len(mapping)
    print(f"\nExtraction complete!")
    print(f"  Fields found: {found_count}/{len(mapping)}")
    print(f"  Data quality score: {data_quality:.1%}")

    if ai_discovered:
        print(f"\nAI discovered {len(ai_discovered)} new concept(s)!")
        _log_ai_discoveries(ai_discovered, result_df, statement_type, ticker, filing_date, most_recent_period, mapping_manager)

    # Log every field that remained unfound after all passes
    if mapping_manager is not None:
        still_unfound = [r['Field'] for r in results if r['Status'] == 'not_found']
        if still_unfound:
            reason = 'ai_disabled' if not use_ai_fallback else 'no_match'
            for field_name in still_unfound:
                mapping_manager.log_missed_concept(
                    ticker=ticker,
                    statement_type=statement_type,
                    reason=reason,
                    filing_date=filing_date,
                    period_end_date=period_end_date,
                    field_name=field_name,
                )

    if mapping_manager:
        mapping_manager.close()

    if data_quality < 0.5:
        print(f"  WARNING: Low data quality (<50%). Check if correct filing was retrieved.")

    return result_df
