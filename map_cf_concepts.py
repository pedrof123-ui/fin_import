#!/usr/bin/env python3
"""
MAPS CF CONCEPTS TO LINE ITEMS USING AI

Usage:
    uv run map_cf_concepts.py
"""
import os
from dotenv import load_dotenv
from datetime import datetime, date
from openai import AsyncOpenAI, OpenAI
import pandas as pd
import asyncio
import json

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
openrouter_model = "x-ai/grok-4.1-fast"
#openrouter_model = "openai/gpt-oss-120b"
#openrouter_model = "moonshotai/kimi-k2.5"

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
    all_cashflow_df = pd.read_csv("all_cashflow_df.csv")
    all_unique_cashflow_df = all_cashflow_df.drop_duplicates(subset=['concept']).reset_index(drop=True)
    all_unique_cashflow_df.describe()

    concepts_list = all_unique_cashflow_df.iloc[:,1:2].values.tolist()

    cashflow_mapping_json = json.dumps(CASH_FLOW_MAPPING)

    # import random

    # # Select 15 random concepts from concepts_list
    # random_concepts = random.sample(concepts_list, min(15, len(concepts_list)))

    i = 0
    grok_response = []
    for concept in concepts_list:

        instructions = f""" You are a finance analyst and expert with SEC EDGAR filings and XBRL concepts.
        You are given a EDGAR financial statement XBRL concept and 
        a JSON file with predifined XBRL concepts to income statement line mappings. 
        Your job is to map the given XBRL concept to the best match income statement line item in the 
        predifined mapping file JSON. Return only the income statement line item that 
        best matches the given XBRL concept. No extra verbage.
        JSON file: {cashflow_mapping_json}
        XBRL concept: {concept}"""

        i += 1 
        
        response = openrouter_client.chat.completions.create(
            model=openrouter_model,
            messages=[{"role": "user", "content": instructions}],
            #NEED TO ADD EXTRA BODY TO FORCE OPENROUTER TO USE CEREBRAS FOR GPT-OSS-120B
            #extra_body=openrouter_extra_body
        )

        print(i," concept", concept[0], "response", response.choices[0].message.content)

        # Initialize oss_response on the first iteration and add each response to a list
        grok_response.append(response.choices[0].message.content)

        if i > 15:
            break


    ## CREATE A LIST OF DICTS WITH THE CONCEPT AND THE RESPONSE
    grok_response_dicts = [
        {"concept": concept[0], "cashflow_mapping": response}
        for concept, response in zip(concepts_list, grok_response)
    ]


    file_path = openrouter_model.rsplit('/', 1)[-1]

    ### SAVE TO FILE
    # Convert oss_response (list) to newline-separated string and save to file
    with open(f"{file_path}_response_dicts.txt", "w") as f:
        f.write("\n".join(str(item) for item in grok_response_dicts))

    print(f"{file_path}_response_dicts.txt", "created")


if __name__ == "__main__":
    main()
