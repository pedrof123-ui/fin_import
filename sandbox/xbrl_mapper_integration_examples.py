"""
Integration Example - Using XBRL Concept Mapper in Helper Functions

This shows how to integrate the AI agent mapping function into your existing
income statement extraction code as a fallback when concepts are not found.
"""

from xbrl_concept_mapper import get_income_statement_mapping
import asyncio


# =============================================================================
# EXAMPLE 1: Simple Integration
# =============================================================================

async def get_concept_field(concept_name: str, mapping: dict) -> str:
    """
    Get the income statement field for a concept
    Falls back to AI agent if not in mapping
    
    Args:
        concept_name: XBRL concept name
        mapping: Dictionary of concept -> field mappings
    
    Returns:
        Field name (e.g., "revenue", "cost_of_revenue")
    """
    # Try to find in existing mapping
    for field, concepts in mapping.items():
        if concept_name in concepts:
            return field
    
    # Not found - use AI agent to map it
    print(f"Concept {concept_name} not in mapping, using AI agent...")
    field = await get_income_statement_mapping(concept_name)
    
    if field and field != "already_mapped":
        print(f"AI agent mapped {concept_name} -> {field}")
        return field
    else:
        print(f"AI agent could not map {concept_name}")
        return None


# =============================================================================
# EXAMPLE 2: Enhanced Field Extraction with AI Fallback
# =============================================================================

async def extract_field_with_ai_fallback(filing, field_name: str, mapping: dict, gaap):
    """
    Extract a field value with AI-powered concept mapping fallback
    
    Args:
        filing: Edgar filing object
        field_name: Income statement field name
        mapping: Concept to field mapping dictionary
        gaap: GAAP namespace prefix
    
    Returns:
        Field value or None
    """
    concepts_to_try = mapping.get(field_name, [])
    
    # Try predefined concepts first
    for concept in concepts_to_try:
        full_concept = f"{gaap}:{concept}"
        try:
            value = filing.financials.income.get_fact(full_concept)
            if value:
                return value
        except:
            continue
    
    # No predefined concept worked - ask AI agent for help
    print(f"No predefined concepts worked for {field_name}")
    print(f"Using AI agent to find unmapped concepts...")
    
    # Get all available concepts from the filing
    available_concepts = get_available_concepts(filing)  # Your existing function
    
    # Ask AI to map each available concept
    for concept in available_concepts:
        ai_field = await get_income_statement_mapping(concept)
        
        if ai_field == field_name:
            # AI found a matching concept!
            print(f"AI found: {concept} maps to {field_name}")
            
            # Try to extract value
            full_concept = f"{gaap}:{concept}"
            try:
                value = filing.financials.income.get_fact(full_concept)
                if value:
                    # Success! Consider adding this to your mapping file
                    print(f"✓ Successfully extracted value using AI-discovered concept")
                    return value
            except:
                continue
    
    return None


# =============================================================================
# EXAMPLE 3: Batch Processing with AI Mapping
# =============================================================================

async def process_unmapped_concepts(unmapped_concepts: list) -> dict:
    """
    Process a batch of unmapped concepts using AI agent
    
    Args:
        unmapped_concepts: List of XBRL concepts not in mapping
    
    Returns:
        Dictionary of {concept: field_name}
    """
    results = {}
    
    print(f"Processing {len(unmapped_concepts)} unmapped concepts...")
    
    for concept in unmapped_concepts:
        field = await get_income_statement_mapping(concept)
        
        if field and field != "already_mapped":
            results[concept] = field
            print(f"  {concept} → {field}")
        else:
            results[concept] = None
            print(f"  {concept} → Could not map")
    
    return results


# =============================================================================
# EXAMPLE 4: Updated Income Statement Extraction (Full Integration)
# =============================================================================

async def extract_income_statement_with_ai(
    filing, 
    ticker: str, 
    filing_type: str,
    year: int = None,
    quarter: int = None,
    use_ai_fallback: bool = True
):
    """
    Extract income statement with optional AI-powered concept mapping
    
    Args:
        filing: Edgar filing object
        ticker: Stock ticker
        filing_type: Type of filing (10-K, 10-Q)
        year: Fiscal year
        quarter: Quarter number (for 10-Q)
        use_ai_fallback: Whether to use AI agent for unmapped concepts
    
    Returns:
        DataFrame with income statement data
    """
    from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING
    
    # Your existing extraction logic here...
    results = {}
    unmapped_concepts_found = []
    
    for field_name in INCOME_STATEMENT_MAPPING.keys():
        # Try predefined mapping first
        value = None
        for concept in INCOME_STATEMENT_MAPPING[field_name]:
            # Try to extract...
            pass  # Your existing code
        
        if value is None and use_ai_fallback:
            # Predefined mapping failed - use AI
            print(f"Using AI fallback for {field_name}...")
            
            # Get available concepts
            available_concepts = []  # Your code to get available concepts
            
            # Ask AI to map
            for concept in available_concepts:
                ai_field = await get_income_statement_mapping(concept)
                if ai_field == field_name:
                    # Found it!
                    unmapped_concepts_found.append({
                        'concept': concept,
                        'field': field_name
                    })
                    # Try to extract value...
                    break
    
    # Report unmapped concepts that were found
    if unmapped_concepts_found:
        print("\n" + "="*80)
        print("UNMAPPED CONCEPTS DISCOVERED BY AI")
        print("="*80)
        print("\nConsider adding these to income_statement_xbrl_mapping.py:")
        for item in unmapped_concepts_found:
            print(f"  '{item['concept']}',  # {item['field']}")
    
    return results  # Your DataFrame


# =============================================================================
# EXAMPLE 5: Simple Helper Function for Your Code
# =============================================================================

async def map_concept_if_not_found(concept: str) -> str:
    """
    Simple helper: map a concept to income statement field
    
    Args:
        concept: XBRL concept name
    
    Returns:
        Field name or None
    
    Usage in your extraction code:
        >>> field = await map_concept_if_not_found("SellingAndMarketingExpense")
        >>> print(field)
        'selling_general_administrative'
    """
    result = await get_income_statement_mapping(concept)
    
    if result == "already_mapped":
        print(f"Concept {concept} is already in mapping file")
        return None
    
    return result


# =============================================================================
# USAGE DEMONSTRATION
# =============================================================================

async def demo():
    """Demonstrate how to use the mapper"""
    
    print("="*80)
    print("XBRL CONCEPT MAPPER - INTEGRATION DEMO")
    print("="*80)
    
    # Example 1: Simple mapping
    print("\n1. Simple concept mapping:")
    concept = "SellingAndMarketingExpense"
    field = await get_income_statement_mapping(concept)
    print(f"   {concept} → {field}")
    
    # Example 2: Batch processing
    print("\n2. Batch processing unmapped concepts:")
    unmapped = [
        "CustomerAcquisitionCost",
        "CloudInfrastructureExpense",
        "SoftwareLicenseFees"
    ]
    results = await process_unmapped_concepts(unmapped)
    
    # Example 3: Integration with existing mapping
    print("\n3. Using with existing mapping:")
    from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING
    
    test_concept = "ResearchAndDevelopmentExpense"
    field = await get_concept_field(test_concept, INCOME_STATEMENT_MAPPING)
    print(f"   {test_concept} → {field}")
    
    print("\n" + "="*80)
    print("DEMO COMPLETE")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(demo())
