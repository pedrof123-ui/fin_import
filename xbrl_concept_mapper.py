"""
XBRL Concept Mapping Agent - Multi-Statement Version
Uses AI agent to map unmapped XBRL concepts to financial statement line items
Integrates with DuckDB database for tracking and auto-promotion

Supports:
- Income Statement
- Balance Sheet
- Cash Flow Statement

Usage:
    from xbrl_concept_mapper import get_statement_mapping
    
    # Map income statement concept
    concept = "SellingAndMarketingExpense"
    line_item = await get_statement_mapping(concept, 'income')
    print(line_item)  # "selling_general_admin"
    
    # Map balance sheet concept
    concept = "PropertyPlantAndEquipmentNet"
    line_item = await get_statement_mapping(concept, 'balance')
    print(line_item)  # "ppe_net"
    
    # Map cash flow concept
    concept = "PaymentsToAcquirePropertyPlantAndEquipment"
    line_item = await get_statement_mapping(concept, 'cashflow')
    print(line_item)  # "capital_expenditures"
"""

import os
import json
import re
from pathlib import Path
from typing import Literal, Optional
from dotenv import load_dotenv
from agents import Agent, Runner, OpenAIChatCompletionsModel, ModelSettings, RunConfig
from agents.mcp import MCPServerStdio
from openai import AsyncOpenAI

# Load environment variables
load_dotenv(override=True)

# Type for statement types
StatementType = Literal['income', 'balance', 'cashflow']

# Global variables for agent setup
_agent = None
_file_server = None
_initialized = False


async def _initialize_agent():
    """Initialize the AI agent and MCP server (called once)"""
    global _agent, _file_server, _initialized
    
    if _initialized:
        return
    
    # Get API keys
    api_key = os.getenv('OPENAI_API_KEY')
    openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    if not openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment variables")

    openrouter_extra_body={
        "provider": {
            "only": ["cerebras"],        # restrict to Cerebras
            "allow_fallbacks": False,    # fail instead of switching providers
        },
    }    
    
    openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_api_key)
    openrouter_model = OpenAIChatCompletionsModel(model="openai/gpt-oss-120b", openai_client=openrouter_client)

    
    # Setup MCP filesystem server
    # IMPORTANT: Restrict to only xbrl_mappings directory for security
    project_path = os.path.abspath(os.path.join(os.getcwd()))
    mappings_path = os.path.join(project_path, "xbrl_mappings")
    
    # Verify the directory exists
    if not os.path.exists(mappings_path):
        raise ValueError(f"xbrl_mappings directory not found at {mappings_path}")
    
    files_params = {
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            mappings_path  # RESTRICTED: Only access xbrl_mappings folder
        ]
    }
    
    _file_server = MCPServerStdio(params=files_params, client_session_timeout_seconds=60)
    
    # Agent instructions
    instructions = """
    You are a certified financial analyst and expert in SEC EDGAR filings and XBRL concepts.
    
    Your task: Map XBRL concepts to the correct financial statement line items.
    
    You have access to THREE mapping files in the xbrl_mappings directory:
    1. income_statement_xbrl_mapping.py - Income statement fields
    2. balance_sheet_xbrl_mapping.py - Balance sheet fields
    3. cash_flow_xbrl_mapping.py - Cash flow statement fields
    
    CRITICAL RULES:
    - You will be told which statement type to search (income, balance, or cashflow)
    - Search ONLY the relevant mapping file for that statement type
    - Return ONLY the field name from the mapping file (e.g., "revenue", "total_assets", "net_cash_operating_activities")
    - If the concept is already in the mapping file, return "already_mapped"
    - If you cannot find a good match, return "no_match"
    - DO NOT return explanations, just the field name
    
    Use the MCP Server tools to read the mapping files.
    """
    
    # Create agent
    # _agent = Agent(
    #     name="XBRL Concept Mapping Agent",
    #     instructions=instructions,
    #     mcp_servers=[_file_server],
    #     model="gpt-4o-mini"
    # )
    _agent = Agent(
        name="XBRL Concept Mapping Agent",
        instructions=instructions,
        mcp_servers=[_file_server],
        model=openrouter_model,
        model_settings=ModelSettings(extra_body=openrouter_extra_body)
    )
    
    # Connect MCP server
    await _file_server.connect()
    
    _initialized = True


async def get_statement_mapping(
    concept: str, 
    statement_type: StatementType
) -> Optional[str]:
    """
    Map an XBRL concept to a financial statement line item using AI agent
    
    Args:
        concept: XBRL concept name (e.g., "SellingAndMarketingExpense")
        statement_type: 'income', 'balance', or 'cashflow'
    
    Returns:
        Financial statement line item field name (e.g., "selling_general_admin")
        or "already_mapped" if concept is already in mapping file
        or "no_match" if no good match found
        or None if mapping fails
    
    Example:
        >>> line_item = await get_statement_mapping("SellingAndMarketingExpense", "income")
        >>> print(line_item)
        'selling_general_admin'
        
        >>> line_item = await get_statement_mapping("PropertyPlantAndEquipmentNet", "balance")
        >>> print(line_item)
        'ppe_net'
    """
    # Initialize agent if needed
    await _initialize_agent()
    
    # Map statement type to filename
    file_mapping = {
        'income': 'income_statement_xbrl_mapping.py',
        'balance': 'balance_sheet_xbrl_mapping.py',
        'cashflow': 'cash_flow_xbrl_mapping.py'
    }
    
    mapping_file = file_mapping[statement_type]
    
    # Create user instructions
    user_instructions = f"""
    You are given the XBRL concept: {concept}
    Statement type: {statement_type}
    
    Task:
    1. Read the file: {mapping_file}
    2. Find the best matching field for the concept "{concept}"
    3. Return ONLY the field name from the mapping dictionary
    
    Examples of correct responses:
    - "revenue"
    - "total_assets"
    - "net_cash_operating_activities"
    - "already_mapped" (if concept already exists in file)
    - "no_match" (if you cannot find a good match)
    
    Return ONLY the field name. No explanations. No extra text.
    """
    
    try:
    # Run agent - TRACING DISABLED FOR OPENROUTER
        result = await Runner.run(_agent, user_instructions, run_config=RunConfig(tracing_disabled=True))
        
        # Extract and clean the response
        response = result.final_output.strip().lower()
        
        # Remove common extra text
        response = response.replace("already mapped", "already_mapped")
        response = response.replace("the field name is", "").strip()
        response = response.replace("the income statement line item is", "").strip()
        response = response.replace("the balance sheet line item is", "").strip()
        response = response.replace("the cash flow line item is", "").strip()
        response = response.replace(":", "").strip()
        response = response.strip('"').strip("'").strip()
        
        print(f"Mapper called: {concept} ({statement_type}) → {response}")
        
        return response
        
    except Exception as e:
        print(f"Error mapping concept {concept} for {statement_type}: {e}")
        return None


def _get_valid_field_names(statement_type: StatementType) -> set:
    """Returns set of valid field names from the mapping dicts"""
    try:
        from xbrl_mappings import (
            INCOME_STATEMENT_MAPPING,
            BALANCE_SHEET_MAPPING,
            CASH_FLOW_MAPPING,
        )
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

    mapping = {
        'income': INCOME_STATEMENT_MAPPING,
        'balance': BALANCE_SHEET_MAPPING,
        'cashflow': CASH_FLOW_MAPPING,
    }
    return set(mapping.get(statement_type, {}).keys())


async def batch_classify_concepts(
    concepts: list,
    statement_type: StatementType,
    chunk_size: int = 20
) -> dict:
    """
    Classify a list of XBRL concepts in batch using the cloud AI agent.

    Instead of calling the agent once per concept, sends chunks of concepts
    and asks for JSON mapping of all at once.

    Args:
        concepts: List of XBRL concept names to classify
        statement_type: 'income', 'balance', or 'cashflow'
        chunk_size: Number of concepts per agent call

    Returns:
        Dict of {concept: field_name} for successfully classified concepts
    """
    if not concepts:
        return {}

    valid_fields = _get_valid_field_names(statement_type)
    if not valid_fields:
        print(f"  No valid field names found for {statement_type}")
        return {}

    # Ensure agent is initialized
    await _initialize_agent()

    file_mapping = {
        'income': 'income_statement_xbrl_mapping.py',
        'balance': 'balance_sheet_xbrl_mapping.py',
        'cashflow': 'cash_flow_xbrl_mapping.py'
    }
    mapping_file = file_mapping[statement_type]
    field_list = ", ".join(sorted(valid_fields))

    merged_results = {}

    for chunk_start in range(0, len(concepts), chunk_size):
        chunk = concepts[chunk_start:chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (len(concepts) + chunk_size - 1) // chunk_size
        print(f"  Batch AI: classifying chunk {chunk_num}/{total_chunks} ({len(chunk)} concepts)...")

        concept_list = "\n".join(f"  - {c}" for c in chunk)

        user_instructions = f"""
    You are classifying multiple XBRL concepts at once for the {statement_type} statement.

    TASK: For each XBRL concept below, find the best matching field name.

    1. Read the file: {mapping_file}
    2. For each concept, find the best matching field name from these valid field names:
       {field_list}
    3. If a concept has no good match, map it to "no_match"

    XBRL CONCEPTS TO CLASSIFY:
    {concept_list}

    RESPONSE FORMAT: Return ONLY a JSON object, no explanations:
    {{"ConceptName1": "field_name1", "ConceptName2": "no_match", "ConceptName3": "field_name3"}}

    Return ONLY the JSON object. No extra text.
    """

        try:
            result = await Runner.run(_agent, user_instructions, run_config=RunConfig(tracing_disabled=True))
            response = result.final_output.strip()

            if not response:
                print(f"  Batch AI: no response for chunk {chunk_num}")
                continue

            # Try to extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if not json_match:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)

            if not json_match:
                print(f"  Batch AI: no JSON found in chunk {chunk_num} response")
                continue

            try:
                parsed = json.loads(json_match.group())
            except json.JSONDecodeError:
                print(f"  Batch AI: malformed JSON in chunk {chunk_num}")
                continue

            # Validate and merge results
            chunk_found = 0
            for concept_name, field_name in parsed.items():
                field_name = str(field_name).strip().lower()
                if field_name != "no_match" and field_name in valid_fields:
                    merged_results[concept_name] = field_name
                    chunk_found += 1

            print(f"  Batch AI: chunk {chunk_num} classified {chunk_found}/{len(chunk)} concepts")

        except Exception as e:
            print(f"  Batch AI: error on chunk {chunk_num}: {e}")
            continue

    return merged_results


# Backward compatibility wrapper for income statements only
async def get_income_statement_mapping(concept: str) -> Optional[str]:
    """
    Backward compatible wrapper for income statement mapping
    
    Args:
        concept: XBRL concept name
    
    Returns:
        Income statement line item or None
    
    Example:
        >>> line_item = await get_income_statement_mapping("SellingAndMarketingExpense")
        >>> print(line_item)
        'selling_general_admin'
    """
    return await get_statement_mapping(concept, 'income')


async def cleanup():
    """Cleanup function to close MCP server connection"""
    global _file_server, _initialized
    
    if _file_server and _initialized:
        try:
            await _file_server.disconnect()
        except Exception:
            pass
        _initialized = False


# Synchronous wrappers for non-async contexts
def get_statement_mapping_sync(concept: str, statement_type: StatementType) -> Optional[str]:
    """
    Synchronous wrapper for get_statement_mapping
    
    Args:
        concept: XBRL concept name
        statement_type: 'income', 'balance', or 'cashflow'
    
    Returns:
        Financial statement line item or None
    
    Example:
        >>> line_item = get_statement_mapping_sync("PropertyPlantAndEquipmentNet", "balance")
        >>> print(line_item)
        'ppe_net'
    """
    import asyncio
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(get_statement_mapping(concept, statement_type))


def get_income_statement_mapping_sync(concept: str) -> Optional[str]:
    """
    Synchronous wrapper for income statement mapping (backward compatible)
    
    Args:
        concept: XBRL concept name
    
    Returns:
        Income statement line item or None
    
    Example:
        >>> line_item = get_income_statement_mapping_sync("SellingAndMarketingExpense")
        >>> print(line_item)
        'selling_general_admin'
    """
    return get_statement_mapping_sync(concept, 'income')


# =============================================================================
# DATABASE INTEGRATION HELPERS
# =============================================================================

async def map_and_log_to_db(
    concept: str,
    statement_type: StatementType,
    ticker: str,
    value: float,
    filing_date: Optional[str] = None,
    period_end_date: Optional[str] = None
) -> Optional[str]:
    """
    Map a concept and log the discovery to the database
    
    Args:
        concept: XBRL concept name
        statement_type: 'income', 'balance', or 'cashflow'
        ticker: Company ticker symbol
        value: The extracted value
        filing_date: Filing date (YYYY-MM-DD)
        period_end_date: Period end date (YYYY-MM-DD)
    
    Returns:
        Field name if mapped successfully, None otherwise
    
    Example:
        >>> field = await map_and_log_to_db(
        ...     "SellingAndMarketingExpense", 
        ...     "income", 
        ...     "AAPL", 
        ...     5000000000
        ... )
    """
    from datetime import date
    
    # Get mapping
    field_name = await get_statement_mapping(concept, statement_type)
    
    if field_name and field_name not in ['already_mapped', 'no_match']:
        # Log to database
        try:
            from xbrl_mapping_manager_multi_statement import XBRLMappingManager
            
            mapper = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')
            
            # Convert dates if provided
            filing_date_obj = date.fromisoformat(filing_date) if filing_date else None
            period_date_obj = date.fromisoformat(period_end_date) if period_end_date else None
            
            await mapper.add_ai_discovery(
                ticker=ticker,
                statement_type=statement_type,
                field_name=field_name,
                concept=concept,
                value=value,
                filing_date=filing_date_obj,
                period_end_date=period_date_obj
            )
            
            mapper.close()
            
            print(f"  Logged AI discovery to database: {concept} → {field_name}")
            
        except Exception as e:
            print(f"  Failed to log to database: {e}")
    
    return field_name


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_mapping():
        """Test the concept mapping function for all statement types"""
        
        print("="*80)
        print("MULTI-STATEMENT XBRL CONCEPT MAPPING TESTS")
        print("="*80)
        
        # Test income statement concepts
        print("\n" + "="*80)
        print("INCOME STATEMENT")
        print("="*80)
        income_concepts = [
            "SellingAndMarketingExpense",
            "ResearchAndDevelopmentExpense",
            "InterestExpense",
            "IncomeTaxExpenseBenefit",
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ]
        
        for concept in income_concepts:
            print(f"\nConcept: {concept}")
            result = await get_statement_mapping(concept, 'income')
            print(f"Mapped to: {result}")
        
        # Test balance sheet concepts
        print("\n" + "="*80)
        print("BALANCE SHEET")
        print("="*80)
        balance_concepts = [
            "PropertyPlantAndEquipmentNet",
            "Assets",
            "AccountsReceivableNetCurrent",
            "LongTermDebtNoncurrent",
            "StockholdersEquity"
        ]
        
        for concept in balance_concepts:
            print(f"\nConcept: {concept}")
            result = await get_statement_mapping(concept, 'balance')
            print(f"Mapped to: {result}")
        
        # Test cash flow concepts
        print("\n" + "="*80)
        print("CASH FLOW STATEMENT")
        print("="*80)
        cashflow_concepts = [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "NetCashProvidedByUsedInOperatingActivities",
            "DepreciationDepletionAndAmortization",
            "PaymentsOfDividends",
            "ProceedsFromIssuanceOfDebt"
        ]
        
        for concept in cashflow_concepts:
            print(f"\nConcept: {concept}")
            result = await get_statement_mapping(concept, 'cashflow')
            print(f"Mapped to: {result}")
        
        # Test database integration
        print("\n" + "="*80)
        print("DATABASE INTEGRATION TEST")
        print("="*80)
        
        field = await map_and_log_to_db(
            concept="SellingAndMarketingExpense",
            statement_type="income",
            ticker="TEST",
            value=1000000000,
            filing_date="2024-02-08",
            period_end_date="2023-12-31"
        )
        print(f"\nLogged to database: {field}")
        
        # Cleanup
        await cleanup()
        
        print("\n" + "="*80)
        print("All tests complete!")
        print("="*80)
    
    # Run tests
    asyncio.run(test_mapping())
