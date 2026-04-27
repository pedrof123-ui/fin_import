#!/usr/bin/env python3
"""
Maps income statement XBRL concepts to line items using AI.

Usage:
    uv run map_inc_concepts.py
"""
import os
from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd
import json
import time

load_dotenv(override=True)
## MAP CONCEPTS TO LINE ITEMS


# CHANGE TO FINANCIAL STATEMENT YOU WANT TO MAP
from xbrl_mappings.income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING

google_api_key = os.getenv('GOOGLE_API_KEY')
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

gemini_client = OpenAI(base_url=GEMINI_BASE_URL, api_key=google_api_key)
gemini_model = "gemini-3-flash-preview"

openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
openrouter_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_api_key)

## CHOOSE OPENROUTER MODEL
#openrouter_model = "stepfun/step-3.5-flash:free"
#openrouter_model = "x-ai/grok-4.1-fast"
#openrouter_model = "openai/gpt-oss-120b"
#openrouter_model = "qwen/qwen3-32b:nitro"
openrouter_model = "arcee-ai/trinity-large-preview:free"
#openrouter_model  = "xiaomi/mimo-v2-flash"
openrouter_decider_model = "anthropic/claude-sonnet-4.5"

#### USE EXTRA BODY TO FORCE OPENROUTER TO USE CEREBRAS FOR GPT-OSS-120B
# openrouter_extra_body={
#     "provider": {
#         "only": ["cerebras"],        # restrict to Cerebras
#         #"only": ["deepinfra"],        # restrict to Cerebras
#         "allow_fallbacks": False,    # fail instead of switching providers
#     },
# }  


def main():
    """Main execution function"""
    #### THIS CODE IMPORTS MAPPINGS PREVIOUSLY EXPORTED FROM THE DATABASE
    ### AND CREATES A LIST OF DICTIONARIES
    with open("data/income_concept_mappings.txt", "r") as f:
        income_concept_mappings = f.read()

    import ast

    # Parse the file content (it's a list of dictionaries)
    income_concept_mappings_list = ast.literal_eval(income_concept_mappings)

    # Extract ai_discovered_concepts from each dictionary in the list
    ai_discovered_list = [
        {"concept": concept, "field_name": item["field_name"]}
        for item in income_concept_mappings_list
        if "ai_discovered_concepts" in item
        for concept in (
            item["ai_discovered_concepts"]
            if isinstance(item["ai_discovered_concepts"], list)
            else [item["ai_discovered_concepts"]]
        )
    ]

    concepts_list = [d["concept"] for d in ai_discovered_list]
    concepts_list = [concept for concept in concepts_list if "Abstract" not in concept]
    concepts_list = [concept.split('_', 1)[1] if '_' in concept else concept for concept in concepts_list]

    income_mapping_json = json.dumps(INCOME_STATEMENT_MAPPING)

    print(f"Mapping {len(concepts_list)} concepts")
   

    # import random

    # # Select 15 random concepts from concepts_list
    # random_concepts = random.sample(concepts_list, min(15, len(concepts_list)))

    ### DON"T FORGET TO CHANGET THE PROMPT FOR THE STATEMENT TYPE
    i = 0
    final_response = []
    for concept in concepts_list:

        instructions = f""" You are a finance analyst and expert with SEC EDGAR filings and XBRL concepts.
        You are given a EDGAR financial statement XBRL concept and 
        a JSON file with predifined income statement line items. 
        Your job is to map the given XBRL concept to the best match income statement line item in the 
        predifined mapping JSON file. Return only the income statement line item that 
        best matches the given XBRL concept. No extra verbage.
        DO NOT RETURN ANYTHING OTHER THAN THE INCOME STATEMENT LINE ITEM. NO EXTRA VERBAGE. NO EXTRA TEXT. NO EXTRA COMMENTS.
        NO BLOCK CODE. 

        JSON file: {income_mapping_json}
        XBRL concept: {concept}
        """

        i += 1 
        rate_limit_delay: float = 1.5
        
        gemini_response = gemini_client.chat.completions.create(
            model=gemini_model,
            messages=[{"role": "user", "content": instructions}],
            #NEED TO ADD EXTRA BODY TO FORCE OPENROUTER TO USE CEREBRAS FOR GPT-OSS-120B
            #extra_body=openrouter_extra_body
        )

        LLM1_response = gemini_response.choices[0].message.content

        openrouter_response = openrouter_client.chat.completions.create(
            model=openrouter_model,
            messages=[{"role": "user", "content": instructions}],
            #NEED TO ADD EXTRA BODY TO FORCE OPENROUTER TO USE CEREBRAS FOR GPT-OSS-120B
            #extra_body=openrouter_extra_body
        )
        
        LLM2_response = openrouter_response.choices[0].message.content

        #if the two LLM responses are different, use the decider LLM to decide which is correct
        if LLM1_response != LLM2_response:

            decider_instructions = f""" You are a finance analyst and expert with SEC EDGAR filings and XBRL concepts.
                Your job is to map the given XBRL concept to the best match income statement line item in the 
                predifined mapping JSON file. You will be given the mappings of a given XBRL concept by two 
                different LLMs. You need to decide which mapping is correct. If both are LLM mappings are incorrect,
                return your own mapping the best matches the concept. 
                No extra verbage. RETURN ONLY THE CORRECT 
                STATEMENT LINE ITEM NO EXTRA VERBAGE. NO EXPLANATION.
                NO EXTRA TEXT. NO EXTRA COMMENTS.
                NO BLOCK CODE. NO EXTRA

                JSON file: {income_mapping_json}
                XBRL concept: {concept}
                LLM1 response: {LLM1_response}
                LLM2 response: {LLM2_response}
                """

            decider_response = openrouter_client.chat.completions.create(  
                model=openrouter_decider_model,
                messages=[{"role": "user", "content": decider_instructions}],
            )

            final_response.append(decider_response.choices[0].message.content)

            print(i,f"{gemini_model}", " concept", concept, "response", LLM1_response)
            print(i,f"{openrouter_model}", " concept", concept, "response", LLM2_response)
            print(i,f"{openrouter_decider_model}", " concept", concept, "response", decider_response.choices[0].message.content)
        else:
            final_response.append(LLM1_response)

            print(i,f"{gemini_model}", " concept", concept, "response", LLM1_response)
            print(i,f"{openrouter_model}", " concept", concept, "response", LLM2_response)

       
        ### RATE LIMITING ###
        time.sleep(rate_limit_delay)

        ### BREAK AFTER 15 CONCEPTS ###

        # if i > 20:
        #     break

     ## CONVERT TO A LIST OF DICTS WITH THE CONCEPT AND THE RESPONSE
    final_response_dicts = [
        {"concept": concept, "income_mapping": response}
        for concept, response in zip(concepts_list, final_response)
    ]

    #file_path = openrouter_model.rsplit('/', 1)[-1]
    #file_path = gemini_model.rsplit('/', -1)[0]
    file_path = "income_st"

    ### SAVE TO FILE
    with open(f"{file_path}_response_dicts.txt", "w") as f:
        f.write("\n".join(str(item) for item in final_response_dicts))

    print(f"{file_path}_response_dicts.txt", "created")


if __name__ == "__main__":
    main()
