#!/usr/bin/env python3
"""
Maps cash flow XBRL concepts to line items using AI.

Usage:
    uv run map_cf_concepts.py
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
from xbrl_mappings.cash_flow_xbrl_mapping import CASH_FLOW_MAPPING

# OLLAMA SETTINGS
# OLLAMA_BASE_URL = "http://172.17.112.1:11434/v1"
# ollama = OpenAI(base_url=OLLAMA_BASE_URL, api_key='ollama')
# ollama_model = "deepseek-r1:8b"

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
    all_cashflow_df = pd.read_csv("data/all_cashflow_df.csv")
    all_unique_cashflow_df = all_cashflow_df.drop_duplicates(subset=['concept']).reset_index(drop=True)
    all_unique_cashflow_df.describe()

    concepts_list = all_unique_cashflow_df.iloc[:,1:2].values.tolist()

    cashflow_mapping_json = json.dumps(CASH_FLOW_MAPPING)

    print(f"using {openrouter_model} to map {len(concepts_list)} concepts")

    

    # import random

    # # Select 15 random concepts from concepts_list
    # random_concepts = random.sample(concepts_list, min(15, len(concepts_list)))

    ### DON"T FORGET TO CHANGET THE PROMPT FOR THE STATEMENT TYPE
    i = 0
    grok_response = []
    for concept in concepts_list:

        instructions = f""" You are a finance analyst and expert with SEC EDGAR filings and XBRL concepts.
        You are given a EDGAR financial statement XBRL concept and 
        a JSON file with predifined cash flow statement line items. 
        Your job is to map the given XBRL concept to the best match cash flow statement line item in the 
        predifined mapping JSON file. Return only the cash flow statement line item that 
        best matches the given XBRL concept. No extra verbage.
        DO NOT RETURN ANYTHING OTHER THAN THE CASH FLOW STATEMENT LINE ITEM. NO EXTRA VERBAGE. NO EXTRA TEXT. NO EXTRA COMMENTS.
        NO BLOCK CODE. 

        JSON file: {cashflow_mapping_json}
        XBRL concept: {concept}
        """

        i += 1 
        rate_limit_delay: float = 1.0
        
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
                Your job is to map the given XBRL concept to the best match cash flow statement line item in the 
                predifined mapping JSON file. You will be given the mapping of a given XBRL concept by two 
                different LLMs. You need to decide which mapping is correct. If both are LLM mappings are incorrect,
                return your own mapping. No extra verbage.
                DO NOT RETURN ANYTHING OTHER THAN THE CASH FLOW STATEMENT LINE ITEM. NO EXTRA VERBAGE. NO EXTRA TEXT. NO EXTRA COMMENTS.
                NO BLOCK CODE. NO EXTRA

                JSON file: {cashflow_mapping_json}
                XBRL concept: {concept}
                LLM1 response: {LLM1_response}
                LLM2 response: {LLM2_response}
                """

            decider_response = openrouter_client.chat.completions.create(  
            model=openrouter_decider_model,
            messages=[{"role": "user", "content": decider_instructions}],
            )

            grok_response.append(decider_response.choices[0].message.content)

            print(i,f"{gemini_model}", " concept", concept[0], "response", LLM1_response)
            print(i,f"{openrouter_model}", " concept", concept[0], "response", LLM2_response)
            print(i,f"{openrouter_decider_model}", " concept", concept[0], "response", decider_response.choices[0].message.content)
        else:
            grok_response.append(LLM1_response)

            print(i,f"{gemini_model}", " concept", concept[0], "response", LLM1_response)
            print(i,f"{openrouter_model}", " concept", concept[0], "response", LLM2_response)

       
        ### RATE LIMITING ###
        time.sleep(rate_limit_delay)

        ### BREAK AFTER 15 CONCEPTS ###
        if i > 15:
            break


    ## CREATE A LIST OF DICTS WITH THE CONCEPT AND THE RESPONSE
    grok_response_dicts = [
        {"concept": concept[0], "cashflow_mapping": response}
        for concept, response in zip(concepts_list, grok_response)
    ]


    #file_path = openrouter_model.rsplit('/', 1)[-1]
    file_path = gemini_model.rsplit('/', -1)[0]

    ### SAVE TO FILE
    # Convert oss_response (list) to newline-separated string and save to file
    with open(f"{file_path}_response_dicts.txt", "w") as f:
        f.write("\n".join(str(item) for item in grok_response_dicts))

    print(f"{file_path}_response_dicts.txt", "created")


if __name__ == "__main__":
    main()
