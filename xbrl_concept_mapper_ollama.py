"""
XBRL Concept Mapping Agent - Ollama Local Model Version
Uses local Ollama models to map XBRL concepts to financial statement line items
Zero API costs, complete privacy

Supports:
- Income Statement
- Balance Sheet
- Cash Flow Statement

Recommended Ollama Models:
- llama3.1:8b (good balance)
- llama3.3:70b (best quality, needs good GPU)
- qwen2.5:14b (very good reasoning)
- mistral:7b (fast, decent quality)

Setup:
    1. Install Ollama: https://ollama.ai
    2. Pull a model: ollama pull llama3.1:8b
    3. Start Ollama: ollama serve (runs automatically on install)

Usage:
    from xbrl_concept_mapper_ollama import get_statement_mapping
    
    # Map income statement concept
    concept = "SellingAndMarketingExpense"
    line_item = await get_statement_mapping(concept, 'income')
    print(line_item)  # "selling_general_admin"
"""

import os
import json
from pathlib import Path
from typing import Literal, Optional
from dotenv import load_dotenv
import httpx
import asyncio

# Load environment variables
load_dotenv(override=True)

# Type for statement types
StatementType = Literal['income', 'balance', 'cashflow']


def get_windows_host_ip() -> str:
    """
    Get Windows host IP address from WSL environment
    
    Returns:
        Windows host IP address or 'localhost' if not in WSL
    """
    try:
        # Check if we're in WSL
        with open('/proc/version', 'r') as f:
            if 'microsoft' in f.read().lower():
                # We're in WSL - get Windows host IP
                import subprocess
                result = subprocess.run(
                    ['ip', 'route', 'show', 'default'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    # Parse output: "default via 172.17.112.1 dev eth0"
                    for line in result.stdout.split('\n'):
                        if 'default' in line:
                            parts = line.split()
                            if 'via' in parts:
                                via_index = parts.index('via')
                                if via_index + 1 < len(parts):
                                    ip = parts[via_index + 1]
                                    print(f"Detected WSL Windows host IP: {ip}")
                                    return ip
    except:
        pass
    
    return 'localhost'


# Ollama configuration with automatic WSL detection
def get_ollama_base_url() -> str:
    """Get Ollama base URL with automatic WSL Windows host detection"""
    # First check if user explicitly set OLLAMA_BASE_URL in environment
    env_url = os.getenv('OLLAMA_BASE_URL')
    if env_url:
        return env_url
    
    # Check if OLLAMA_HOST is set (this takes precedence)
    ollama_host = os.getenv('OLLAMA_HOST')
    if ollama_host:
        return ollama_host
    
    # Auto-detect Windows host if in WSL
    host = get_windows_host_ip()
    return f'http://{host}:11434'


OLLAMA_BASE_URL = get_ollama_base_url()
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'deepseek-r1:8b')
OLLAMA_TIMEOUT = float(os.getenv('OLLAMA_TIMEOUT', '60.0'))  # 60 seconds default

print(f"Ollama configuration: {OLLAMA_BASE_URL} (model: {OLLAMA_MODEL})")


def read_mapping_file(statement_type: StatementType) -> str:
    """Read the mapping file content for a statement type"""
    file_mapping = {
        'income': 'income_statement_xbrl_mapping.py',
        'balance': 'balance_sheet_xbrl_mapping.py',
        'cashflow': 'cash_flow_xbrl_mapping.py'
    }
    
    filename = file_mapping[statement_type]
    
    # Try multiple possible locations
    possible_paths = [
        # 1. Relative to current working directory
        os.path.join(os.getcwd(), "xbrl_mappings", filename),
        # 2. Relative to this script's location
        os.path.join(os.path.dirname(__file__), "xbrl_mappings", filename),
        # 3. Parent directory of this script
        os.path.join(os.path.dirname(__file__), "..", "xbrl_mappings", filename),
        # 4. Same directory as this script
        os.path.join(os.path.dirname(__file__), filename),
        # 5. Uploaded files directory
        os.path.join("/mnt/user-data/uploads", "xbrl_mappings", filename),
        os.path.join("/mnt/user-data/uploads", filename),
        # 6. Output files directory
        os.path.join("/mnt/user-data/outputs", filename),
    ]
    
    # Try each path
    for file_path in possible_paths:
        normalized_path = os.path.abspath(file_path)
        if os.path.exists(normalized_path):
            with open(normalized_path, 'r') as f:
                content = f.read()
                return content
    
    # If not found, provide helpful error
    raise ValueError(
        f"❌ Mapping file not found: {filename}\n\n"
        f"Searched in:\n" + 
        "\n".join(f"  • {os.path.abspath(p)}" for p in possible_paths) +
        f"\n\n📁 Current working directory: {os.getcwd()}\n"
        f"📍 Script location: {os.path.dirname(os.path.abspath(__file__))}\n\n"
        f"💡 Fix: Run 'python setup_project.py' to organize files"
    )


async def call_ollama(prompt: str, model: str = OLLAMA_MODEL, timeout: float = OLLAMA_TIMEOUT, num_predict: int = 50) -> Optional[str]:
    """
    Call Ollama API with the given prompt

    Args:
        prompt: The prompt to send
        model: Ollama model to use
        timeout: Timeout in seconds
        num_predict: Max tokens to generate

    Returns:
        Model response or None on error
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temperature for consistent outputs
                        "top_p": 0.9,
                        "num_predict": num_predict
                    }
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '').strip()
            else:
                print(f"Ollama API error: {response.status_code} - {response.text}")
                return None
                
    except httpx.TimeoutException:
        print(f"Ollama timeout after {timeout}s")
        return None
    except Exception as e:
        print(f"Ollama error: {e}")
        return None


async def get_statement_mapping(
    concept: str, 
    statement_type: StatementType
) -> Optional[str]:
    """
    Map an XBRL concept to a financial statement line item using local Ollama model
    
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
    """
    
    # Read mapping file content
    try:
        mapping_content = read_mapping_file(statement_type)
    except Exception as e:
        print(f"Error reading mapping file: {e}")
        return None
    
    # Check if concept is already in the file
    if concept in mapping_content:
        print(f"Mapper called: {concept} ({statement_type}) → already_mapped")
        return "already_mapped"
    
    # Create prompt for Ollama
    prompt = f"""You are a financial analyst mapping XBRL concepts to standardized field names.

TASK: Map the XBRL concept "{concept}" to a field name from the {statement_type} mapping file below.

MAPPING FILE:
{mapping_content}

INSTRUCTIONS:
1. Find the best matching field name for the concept "{concept}"
2. Return ONLY the field name (e.g., "revenue" or "total_assets")
3. If the concept is already in the mapping file, return "already_mapped"
4. If you cannot find a good match, return "no_match"
5. Do NOT include any explanation, just the field name

RESPONSE FORMAT: Return only one of:
- A field name from the dictionary (e.g., "selling_general_admin")
- "already_mapped"
- "no_match"

CONCEPT TO MAP: {concept}
YOUR RESPONSE (field name only):"""

    try:
        # Call Ollama
        response = await call_ollama(prompt, model=OLLAMA_MODEL, timeout=OLLAMA_TIMEOUT)
        
        if not response:
            return None
        
        # Clean response
        response = response.strip().lower()
        response = response.replace("already mapped", "already_mapped")
        response = response.replace("the field name is", "").strip()
        response = response.replace("the income statement line item is", "").strip()
        response = response.replace("the balance sheet line item is", "").strip()
        response = response.replace("the cash flow line item is", "").strip()
        response = response.replace(":", "").strip()
        response = response.strip('"').strip("'").strip()
        
        # Remove any trailing punctuation or explanations
        if '\n' in response:
            response = response.split('\n')[0].strip()
        
        print(f"Mapper called: {concept} ({statement_type}) → {response}")
        
        return response
        
    except Exception as e:
        print(f"Error mapping concept {concept} for {statement_type}: {e}")
        return None


import re

def _strip_think_tags(text: str) -> str:
    """Strip <think>...</think> tags from deepseek-r1 output"""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


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
    chunk_size: int = 8
) -> dict:
    """
    Classify a list of XBRL concepts in batch using Ollama.

    Instead of calling Ollama once per concept, sends chunks of concepts
    and asks for JSON mapping of all at once.

    Args:
        concepts: List of XBRL concept names to classify
        statement_type: 'income', 'balance', or 'cashflow'
        chunk_size: Number of concepts per Ollama call

    Returns:
        Dict of {concept: field_name} for successfully classified concepts
    """
    if not concepts:
        return {}

    valid_fields = _get_valid_field_names(statement_type)
    if not valid_fields:
        print(f"  No valid field names found for {statement_type}")
        return {}

    merged_results = {}

    # Process in chunks
    for chunk_start in range(0, len(concepts), chunk_size):
        chunk = concepts[chunk_start:chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (len(concepts) + chunk_size - 1) // chunk_size
        print(f"  Batch AI: classifying chunk {chunk_num}/{total_chunks} ({len(chunk)} concepts)...")

        concept_list = "\n".join(f"  - {c}" for c in chunk)
        field_list = ", ".join(sorted(valid_fields))

        prompt = f"""Map each XBRL concept to the best matching {statement_type} statement field name.

VALID FIELD NAMES: {field_list}

CONCEPTS:
{concept_list}

Rules: Return JSON only. Use "no_match" if no good match. No explanations.
Format: {{"ConceptName": "field_name", ...}}"""

        try:
            response = await call_ollama(
                prompt,
                model=OLLAMA_MODEL,
                timeout=120.0,
                num_predict=1500
            )

            if not response:
                print(f"  Batch AI: no response for chunk {chunk_num}")
                continue

            # Strip think tags (deepseek-r1)
            response = _strip_think_tags(response)

            # Try to extract JSON from response
            # Look for JSON object in the response
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if not json_match:
                # Try multiline JSON with nested braces
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
    """
    return await get_statement_mapping(concept, 'income')


async def check_ollama_available() -> bool:
    """
    Check if Ollama is running and model is available
    
    Returns:
        True if Ollama is ready, False otherwise
    """
    print(f"\nChecking Ollama availability...")
    print(f"  URL: {OLLAMA_BASE_URL}")
    print(f"  Model: {OLLAMA_MODEL}")
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check if Ollama is running
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            
            if response.status_code != 200:
                print(f"❌ Ollama not responding (status {response.status_code})")
                return False
            
            # Check if our model is available
            models = response.json().get('models', [])
            model_names = [m['name'] for m in models]
            
            if OLLAMA_MODEL not in model_names:
                print(f"❌ Model '{OLLAMA_MODEL}' not found in Ollama")
                print(f"   Available models: {', '.join(model_names)}")
                print(f"   Run: ollama pull {OLLAMA_MODEL}")
                return False
            
            print(f"✅ Ollama ready with model: {OLLAMA_MODEL}")
            return True
            
    except httpx.ConnectError as e:
        print(f"❌ Cannot connect to Ollama at {OLLAMA_BASE_URL}")
        print(f"   Error: {e}")
        print(f"\n   Troubleshooting for WSL:")
        print(f"   1. Check Ollama is running on Windows")
        print(f"   2. Verify firewall allows WSL connections")
        print(f"   3. Test: nc -zv $(ip route | awk '/default/ {{print $3}}') 11434")
        return False
    except Exception as e:
        print(f"❌ Error checking Ollama: {e}")
        return False


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_mapping():
        """Test the concept mapping function with Ollama"""
        
        print("="*80)
        print("OLLAMA XBRL CONCEPT MAPPING TESTS")
        print("="*80)
        print(f"Using model: {OLLAMA_MODEL}")
        print(f"Ollama URL: {OLLAMA_BASE_URL}")
        print()
        
        # Check if Ollama is available
        if not await check_ollama_available():
            print("\n❌ Ollama setup required. Please:")
            print("   1. Install Ollama: https://ollama.ai")
            print(f"   2. Pull model: ollama pull {OLLAMA_MODEL}")
            print("   3. Start Ollama: ollama serve")
            return
        
        print()
        
        # Test income statement concepts
        print("="*80)
        print("INCOME STATEMENT")
        print("="*80)
        income_concepts = [
            "SellingAndMarketingExpense",
            "ResearchAndDevelopmentExpense",
            "InterestExpense"
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
            "AccountsReceivableNetCurrent"
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
            "DepreciationDepletionAndAmortization"
        ]
        
        for concept in cashflow_concepts:
            print(f"\nConcept: {concept}")
            result = await get_statement_mapping(concept, 'cashflow')
            print(f"Mapped to: {result}")
        
        print("\n" + "="*80)
        print("Tests complete!")
        print("="*80)
    
    # Run tests
    asyncio.run(test_mapping())
