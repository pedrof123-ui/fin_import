"""
MCP Server Diagnostic Script
Tests the AI concept mapper and MCP server connection
"""

import asyncio
import os
from dotenv import load_dotenv

# Load environment
load_dotenv(override=True)

print("="*80)
print("MCP SERVER DIAGNOSTIC")
print("="*80)

# =============================================================================
# Test 1: Check Environment Variables
# =============================================================================

print("\n1. CHECKING ENVIRONMENT VARIABLES")
print("-"*80)

openai_key = os.getenv('OPENAI_API_KEY')
if openai_key:
    print(f"✓ OPENAI_API_KEY found: {openai_key[:10]}...{openai_key[-5:]}")
else:
    print("✗ OPENAI_API_KEY not found!")

# =============================================================================
# Test 2: Check if xbrl_concept_mapper can be imported
# =============================================================================

print("\n2. IMPORTING xbrl_concept_mapper")
print("-"*80)

try:
    from xbrl_concept_mapper import get_income_statement_mapping
    print("✓ Successfully imported get_income_statement_mapping")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    exit(1)

# =============================================================================
# Test 3: Test MCP Server Initialization
# =============================================================================

print("\n3. TESTING MCP SERVER INITIALIZATION")
print("-"*80)

async def test_initialization():
    """Test if MCP server initializes"""
    try:
        from xbrl_concept_mapper import _initialize_agent
        
        print("Initializing AI agent and MCP server...")
        await _initialize_agent()
        print("✓ MCP server initialized successfully")
        return True
        
    except Exception as e:
        print(f"✗ Initialization failed: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False

# =============================================================================
# Test 4: Test Simple Concept Mapping
# =============================================================================

print("\n4. TESTING SIMPLE CONCEPT MAPPING")
print("-"*80)

async def test_simple_mapping():
    """Test mapping a known concept"""
    
    test_concepts = [
        "ResearchAndDevelopmentExpense",
        "SellingAndMarketingExpense",
        "InterestExpense"
    ]
    
    print(f"\nTesting {len(test_concepts)} concept mappings...\n")
    
    results = []
    
    for concept in test_concepts:
        print(f"Testing: {concept}")
        try:
            result = await get_income_statement_mapping(concept)
            print(f"  ✓ Result: {result}")
            results.append((concept, result, None))
        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            print(f"  ✗ Error: {error_msg}")
            print(f"     Type: {type(e).__name__}")
            results.append((concept, None, e))
    
    return results

# =============================================================================
# Test 5: Test Unmapped Concept
# =============================================================================

print("\n5. TESTING UNMAPPED CONCEPT")
print("-"*80)

async def test_unmapped_concept():
    """Test a concept that's NOT in the mapping"""
    
    # These are real XBRL concepts but not in our mapping
    unmapped_concepts = [
        "FinancingInterestExpense",
        "GoodwillImpairmentLoss"
    ]
    
    print(f"\nTesting {len(unmapped_concepts)} unmapped concepts...\n")
    
    results = []
    
    for concept in unmapped_concepts:
        print(f"Testing: {concept}")
        try:
            result = await get_income_statement_mapping(concept)
            print(f"  ✓ Result: {result}")
            results.append((concept, result, None))
        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            print(f"  ✗ Error: {error_msg}")
            print(f"     Type: {type(e).__name__}")
            results.append((concept, None, e))
    
    return results

# =============================================================================
# Test 6: Test Multiple Sequential Calls
# =============================================================================

print("\n6. TESTING MULTIPLE SEQUENTIAL CALLS")
print("-"*80)

async def test_sequential_calls():
    """Test if server handles multiple calls properly"""
    
    print("\nMaking 5 sequential calls...\n")
    
    success_count = 0
    fail_count = 0
    
    for i in range(5):
        print(f"Call {i+1}/5: ResearchAndDevelopmentExpense")
        try:
            result = await get_income_statement_mapping("ResearchAndDevelopmentExpense")
            print(f"  ✓ Success: {result}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed: {type(e).__name__}")
            fail_count += 1
    
    print(f"\nResults: {success_count} successes, {fail_count} failures")
    return success_count, fail_count

# =============================================================================
# Test 7: Check MCP Server Connection Details
# =============================================================================

print("\n7. CHECKING MCP SERVER DETAILS")
print("-"*80)

async def check_mcp_details():
    """Check MCP server configuration"""
    try:
        from xbrl_concept_mapper import _file_server, _agent, _initialized
        
        print(f"Initialized: {_initialized}")
        print(f"File Server: {_file_server}")
        print(f"Agent: {_agent}")
        
        if _file_server:
            print(f"  Server params: {_file_server.params if hasattr(_file_server, 'params') else 'N/A'}")
        
        return True
    except Exception as e:
        print(f"✗ Error checking details: {e}")
        return False

# =============================================================================
# Run All Tests
# =============================================================================

async def run_all_tests():
    """Run all diagnostic tests"""
    
    print("\n" + "="*80)
    print("RUNNING DIAGNOSTIC TESTS")
    print("="*80)
    
    # Test 3: Initialization
    init_success = await test_initialization()
    
    if not init_success:
        print("\n✗ MCP server initialization failed. Cannot continue.")
        return
    
    # Test 4: Simple mapping
    print("\n" + "="*80)
    simple_results = await test_simple_mapping()
    
    # Test 5: Unmapped concepts
    print("\n" + "="*80)
    unmapped_results = await test_unmapped_concept()
    
    # Test 6: Sequential calls
    print("\n" + "="*80)
    success, fail = await test_sequential_calls()
    
    # Test 7: MCP details
    print("\n" + "="*80)
    await check_mcp_details()
    
    # Summary
    print("\n" + "="*80)
    print("DIAGNOSTIC SUMMARY")
    print("="*80)
    
    simple_success = sum(1 for _, result, error in simple_results if error is None)
    unmapped_success = sum(1 for _, result, error in unmapped_results if error is None)
    
    print(f"\nSimple mappings: {simple_success}/{len(simple_results)} successful")
    print(f"Unmapped concepts: {unmapped_success}/{len(unmapped_results)} successful")
    print(f"Sequential calls: {success}/5 successful")
    
    if simple_success == len(simple_results) and success == 5:
        print("\n✓ MCP SERVER IS WORKING CORRECTLY")
    else:
        print("\n✗ MCP SERVER HAS ISSUES")
        
        # Show detailed errors
        print("\nErrors encountered:")
        for concept, result, error in simple_results + unmapped_results:
            if error:
                print(f"  {concept}: {type(error).__name__} - {error}")
    
    # Cleanup
    print("\n" + "="*80)
    print("CLEANUP")
    print("="*80)
    
    try:
        from xbrl_concept_mapper import cleanup
        await cleanup()
        print("✓ Cleaned up MCP server connection")
    except Exception as e:
        print(f"⚠ Cleanup warning: {e}")

# Run diagnostics
if __name__ == "__main__":
    asyncio.run(run_all_tests())