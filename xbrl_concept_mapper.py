"""
XBRL Concept Mapping Agent - Callable Function
Uses AI agent to map unmapped XBRL concepts to income statement line items

Usage:
    from xbrl_concept_mapper import get_income_statement_mapping
    
    concept = "SellingAndMarketingExpense"
    line_item = await get_income_statement_mapping(concept)
    print(line_item)  # "selling_general_administrative"
"""

import os
from dotenv import load_dotenv
from agents import Agent, Runner
from agents.mcp import MCPServerStdio
from openai import AsyncOpenAI

# Load environment variables
load_dotenv(override=True)

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
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    
    # Setup MCP filesystem server
    project_path = os.path.abspath(os.path.join(os.getcwd()))
    
    files_params = {
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            project_path
        ]
    }
    
    _file_server = MCPServerStdio(params=files_params, client_session_timeout_seconds=60)
    
    # Agent instructions
    instructions = """
    You are a certified financial analyst and expert of SEC EDGAR filings and XBRL concepts.
    You are given a financial statement XBRL concept and must find the best match against a predefined 
    income statement line item for a company. The file with the mapping is income_statement_xbrl_mapping.py.
    The file already has the mapping for the most common concepts.
    Use MCP Server tools to access income_statement_xbrl_mapping.py
    """
    
    # Create agent
    _agent = Agent(
        name="XBRL Concept Mapping Agent",
        instructions=instructions,
        mcp_servers=[_file_server],
        model="gpt-4o-mini"
    )
    
    # Connect MCP server
    await _file_server.connect()
    
    _initialized = True


async def get_income_statement_mapping(concept: str) -> str:
    """
    Map an XBRL concept to an income statement line item using AI agent
    
    Args:
        concept: XBRL concept name (e.g., "SellingAndMarketingExpense")
    
    Returns:
        Income statement line item (e.g., "selling_general_administrative")
        or "already_mapped" if concept is already in mapping file
        or None if mapping fails
    
    Example:
        >>> line_item = await get_income_statement_mapping("SellingAndMarketingExpense")
        >>> print(line_item)
        'selling_general_administrative'
    """
    # Initialize agent if needed
    await _initialize_agent()
    
    # Create user instructions
    user_instructions = f"""
    You are given the XBRL concept: {concept}
    
    Map the given XBRL concept to the best match income statement category line item in the predefined mapping file
    income_statement_xbrl_mapping.py.
    
    Return ONLY the income statement line item field name from the mapping file (e.g., "revenue", "cost_of_revenue", 
    "selling_general_administrative", etc.) without any extra verbiage.
    
    If the concept is already mapped in the file, return ONLY the income statement line item field name from the mapping file without any extra verbiage.
    
    Rules:
    - Return only the field name, nothing else
    - No explanations, no punctuation, no extra text
    - Just the field name or "already_mapped"
    """
    
    try:
        # Run agent
        result = await Runner.run(_agent, user_instructions)
        
        # Extract and clean the response
        response = result.final_output.strip().lower()
        
        # Remove common extra text
        response = response.replace("already mapped", "already_mapped")
        response = response.replace("the income statement line item is", "").strip()
        response = response.replace("the field name is", "").strip()
        response = response.replace(":", "").strip()
        response = response.strip('"').strip("'").strip()
        print("Mapper called for concept: ", concept)
        return response
        
    except Exception as e:
        print(f"Error mapping concept {concept}: {e}")
        return None


async def cleanup():
    """Cleanup function to close MCP server connection"""
    global _file_server, _initialized
    
    if _file_server and _initialized:
        try:
            await _file_server.disconnect()
        except:
            pass
        _initialized = False


# Synchronous wrapper for non-async contexts
def get_income_statement_mapping_sync(concept: str) -> str:
    """
    Synchronous wrapper for get_income_statement_mapping
    
    Args:
        concept: XBRL concept name
    
    Returns:
        Income statement line item or None
    
    Example:
        >>> line_item = get_income_statement_mapping_sync("SellingAndMarketingExpense")
        >>> print(line_item)
        'selling_general_administrative'
    """
    import asyncio
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(get_income_statement_mapping(concept))


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_mapping():
        """Test the concept mapping function"""
        
        print("="*80)
        print("XBRL CONCEPT MAPPING TESTS")
        print("="*80)
        
        # Test cases
        test_concepts = [
            "SellingAndMarketingExpense",
            "ResearchAndDevelopmentExpense",
            "InterestExpense",
            "IncomeTaxExpenseBenefit",
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ]
        
        for concept in test_concepts:
            print(f"\nConcept: {concept}")
            result = await get_income_statement_mapping(concept)
            print(f"Mapped to: {result}")
        
        # Cleanup
        await cleanup()
    
    # Run tests
    asyncio.run(test_mapping())
