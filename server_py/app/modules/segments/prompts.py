"""Prompt text for POST /api/segments/generate. Originally ported byte-for-byte in Spanish
from server/routes.ts's handler (~lines 1084-1134); translated to English so every prompt
in this codebase is consistently English. Keep the JSON response contract and the numbered
rules exact — segments/service.py's response parsing relies on the field names below.
"""

SYSTEM_PROMPT = """You are an expert in customer segmentation for retail and e-commerce.
Your task is to analyze the BigQuery data structure and recommend ONE valuable customer segment.

You must ALWAYS respond in JSON format with this exact structure:
{
  "segmentName": "Segment name in English",
  "description": "Detailed segment description in English (2-3 sentences)",
  "segmentType": "churn_risk|high_value|new_customers|frequent_buyers|inactive",
  "criteria": {
    "explanation": "Explanation of the criteria used",
    "confidence": 0.85
  },
  "sql": "SELECT customer_id, email, ... FROM table WHERE conditions LIMIT 10000"
}

CRITICAL RULES for the SQL:
1. ALWAYS use fully-qualified references with backticks: `project.dataset.table`
2. ALWAYS include customer_id or the main identifier field
3. ALWAYS include email if it exists in the schema
4. ALWAYS include the customer's name (name, first_name/last_name) and phone if they exist in the schema - these fields are REQUIRED for CRM integration
5. ALWAYS append LIMIT 10000 at the end (up to 10,000 results are allowed)
6. SELECT only, never modifications
7. The SQL must be directly executable in BigQuery
8. USE ONLY the fields that appear in the provided schema - DO NOT invent fields like 'balance', 'saldo', 'total_spent' if they don't exist
9. If you need to calculate totals, use SUM() over existing numeric fields like 'amount'
10. For active subscriptions, use status = 'active'
11. For dates, use existing fields like 'created' or 'current_period_end'
12. PRODUCT/TIER MAPPING - When the user mentions a tier or product by name, use the corresponding product_id:
  - "Basic Wash" = product_id 'prod_LQjx67EvzQ1PGQ'
  - "Premium Wash" = product_id 'prod_LQjy3uY1m2leN3'
  - "BW/Road Assistance" (monthly) = product_id 'prod_QokBj7SE3bnVgn'
  - "BW/Road Assistance Yearly" = product_id 'prod_TEj2sqBLZUBBby'
  Always filter by product_id (not by name) when the user asks about a specific tier/plan."""


def build_user_prompt(schema_prompt: str, existing_segment_names: list[str]) -> str:
    """Port of the template literal built from `schemaPrompt` and `existingSegmentNames`."""
    existing_block = ""
    if existing_segment_names:
        names_list = "\n".join(f'- "{n}"' for n in existing_segment_names)
        existing_block = f"""
IMPORTANT: These segments already exist, DO NOT repeat them or use similar names:
{names_list}

You must generate a DIFFERENT and UNIQUE segment that isn't in the list above.
"""

    return f"""Analyze this data structure and recommend a valuable customer segment:

{schema_prompt}

{existing_block}

Based on the available tables, identify a customer segment that would be valuable for marketing campaigns.
Generate the SQL to retrieve the segment's members."""
