"""
XBRL Concept Mapping - Maps unmapped XBRL concepts to financial statement fields.
Uses Claude Haiku for batch classification and writes discoveries back to static mapping files.
"""

import json
import re
from pathlib import Path
from typing import Literal, Optional

from openai import AsyncOpenAI

StatementType = Literal['income', 'balance', 'cashflow']

_MAPPING_FILES = {
    'income': 'xbrl_mappings/income_statement_xbrl_mapping.py',
    'balance': 'xbrl_mappings/balance_sheet_xbrl_mapping.py',
    'cashflow': 'xbrl_mappings/cash_flow_xbrl_mapping.py',
}

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        import os
        from dotenv import load_dotenv
        load_dotenv(override=True)
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to your .env file or environment before enabling AI fallback."
            )
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
    return _client


def _get_valid_field_names(statement_type: StatementType) -> set:
    try:
        from xbrl_mappings import INCOME_STATEMENT_MAPPING, BALANCE_SHEET_MAPPING, CASH_FLOW_MAPPING
    except ImportError:
        from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING
        try:
            from balance_sheet_xbrl_mapping import BALANCE_SHEET_MAPPING
        except ImportError:
            BALANCE_SHEET_MAPPING = {}
        try:
            from cash_flow_xbrl_mapping import CASH_FLOW_MAPPING
        except ImportError:
            CASH_FLOW_MAPPING = {}

    mapping = {'income': INCOME_STATEMENT_MAPPING, 'balance': BALANCE_SHEET_MAPPING, 'cashflow': CASH_FLOW_MAPPING}
    return set(mapping.get(statement_type, {}).keys())


def _read_mapping_file(statement_type: StatementType) -> str:
    path = Path(_MAPPING_FILES[statement_type])
    return path.read_text() if path.exists() else ""


async def batch_classify_concepts(
    concepts: list,
    statement_type: StatementType,
    chunk_size: int = 20,
) -> dict:
    """Classify unmapped XBRL concepts using Claude Haiku. Returns {concept: field_name}."""
    if not concepts:
        return {}

    valid_fields = _get_valid_field_names(statement_type)
    if not valid_fields:
        return {}

    mapping_content = _read_mapping_file(statement_type)
    field_list = ", ".join(sorted(valid_fields))
    client = _get_client()
    merged_results = {}

    for chunk_start in range(0, len(concepts), chunk_size):
        chunk = concepts[chunk_start:chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (len(concepts) + chunk_size - 1) // chunk_size
        print(f"  Batch AI: classifying chunk {chunk_num}/{total_chunks} ({len(chunk)} concepts)...")

        concept_list = "\n".join(f"  - {c}" for c in chunk)

        try:
            message = await client.chat.completions.create(
                model="anthropic/claude-haiku-4-5",
                max_tokens=1024,
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are an expert in SEC EDGAR XBRL financial concepts.
Map each XBRL concept to the correct field name from the {statement_type} statement mapping.

Reference mapping file:
{mapping_content}

Valid field names: {field_list}

Rules:
- Return ONLY a JSON object
- Map each concept to its best matching field name
- Use "no_match" if no good match exists""",
                    },
                    {
                        "role": "user",
                        "content": f"Map these XBRL concepts to field names:\n{concept_list}\n\nReturn ONLY JSON: {{\"ConceptName\": \"field_name\", ...}}",
                    },
                ],
            )

            response = message.choices[0].message.content.strip()
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                print(f"  Batch AI: no JSON found in chunk {chunk_num} response")
                continue

            parsed = json.loads(json_match.group())
            chunk_found = 0
            for concept_name, field_name in parsed.items():
                field_name = str(field_name).strip().lower()
                if field_name != "no_match" and field_name in valid_fields:
                    merged_results[concept_name] = field_name
                    chunk_found += 1

            print(f"  Batch AI: chunk {chunk_num} classified {chunk_found}/{len(chunk)} concepts")

        except Exception as e:
            print(f"  Batch AI: error on chunk {chunk_num}: {e}")

    return merged_results


async def get_statement_mapping(concept: str, statement_type: StatementType) -> Optional[str]:
    """Map a single XBRL concept to a field name."""
    results = await batch_classify_concepts([concept], statement_type)
    return results.get(concept)


def write_concept_to_mapping(
    concept: str,
    field_name: str,
    statement_type: StatementType,
    ticker: str = "",
) -> bool:
    """Append a newly discovered concept to the static mapping file."""
    path = Path(_MAPPING_FILES.get(statement_type, ""))
    if not path.exists():
        return False

    content = path.read_text()

    if f'"{concept}"' in content:
        return False

    field_pos = content.find(f'"{field_name}":')
    if field_pos == -1:
        return False

    close_pos = content.find('    ],', field_pos)
    if close_pos == -1:
        return False

    comment = f"  # {ticker} (AI-discovered)" if ticker else "  # AI-discovered"
    new_line = f'        "{concept}",{comment}\n'
    path.write_text(content[:close_pos] + new_line + content[close_pos:])
    print(f"  Written to mapping: {concept} -> {field_name}")
    return True


# Backward compatibility wrappers
async def get_income_statement_mapping(concept: str) -> Optional[str]:
    return await get_statement_mapping(concept, 'income')


def get_statement_mapping_sync(concept: str, statement_type: StatementType) -> Optional[str]:
    import asyncio
    return asyncio.run(get_statement_mapping(concept, statement_type))


def get_income_statement_mapping_sync(concept: str) -> Optional[str]:
    return get_statement_mapping_sync(concept, 'income')


async def cleanup():
    pass


async def map_and_log_to_db(
    concept: str,
    statement_type: StatementType,
    ticker: str,
    value: float,
    filing_date: Optional[str] = None,
    period_end_date: Optional[str] = None,
) -> Optional[str]:
    from datetime import date

    field_name = await get_statement_mapping(concept, statement_type)
    if field_name and field_name not in ['already_mapped', 'no_match']:
        try:
            from xbrl_mapping_manager_multi_statement import XBRLMappingManager
            mapper = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')
            filing_date_obj = date.fromisoformat(filing_date) if filing_date else None
            period_date_obj = date.fromisoformat(period_end_date) if period_end_date else None
            await mapper.add_ai_discovery(
                ticker=ticker,
                statement_type=statement_type,
                field_name=field_name,
                concept=concept,
                value=value,
                filing_date=filing_date_obj,
                period_end_date=period_date_obj,
            )
            mapper.close()
        except Exception as e:
            print(f"  Failed to log to database: {e}")
    return field_name
