"""Exact prompt text ported from server/routes.ts's POST /api/segments/generate handler
(~lines 1084-1134). Do not paraphrase — the JSON response contract and the wording of the
rules below are relied on by the model; keep this byte-for-byte identical to the TS source.
"""

SYSTEM_PROMPT = """Eres un experto en segmentación de clientes para retail y e-commerce.
Tu tarea es analizar la estructura de datos de BigQuery y recomendar UN segmento de clientes valioso.

Debes responder SIEMPRE en formato JSON con esta estructura exacta:
{
  "segmentName": "Nombre del segmento en español",
  "description": "Descripción detallada del segmento en español (2-3 oraciones)",
  "segmentType": "churn_risk|high_value|new_customers|frequent_buyers|inactive",
  "criteria": {
    "explanation": "Explicación de los criterios usados",
    "confidence": 0.85
  },
  "sql": "SELECT customer_id, email, ... FROM table WHERE conditions LIMIT 10000"
}

REGLAS CRÍTICAS para el SQL:
1. SIEMPRE usa referencias completas con backticks: `project.dataset.table`
2. SIEMPRE incluye customer_id o el campo identificador principal
3. SIEMPRE incluye email si existe en el schema
4. SIEMPRE incluye el nombre del cliente (name, first_name/last_name) y teléfono/phone si existen en el schema - estos campos son OBLIGATORIOS para la integración con CRM
5. SIEMPRE agrega LIMIT 10000 al final (permitimos hasta 10,000 resultados)
6. Solo SELECT, nunca modificaciones
7. El SQL debe ser ejecutable directamente en BigQuery
8. USA SOLO los campos que aparecen en el schema proporcionado - NO inventes campos como 'balance', 'saldo', 'total_spent' si no existen
9. Si necesitas calcular totales, usa SUM() sobre campos numéricos existentes como 'amount'
10. Para suscripciones activas, usa status = 'active'
11. Para fechas, usa campos existentes como 'created' o 'current_period_end'
12. MAPEO DE PRODUCTOS/TIERS - Cuando el usuario mencione un tier o producto por nombre, usa el product_id correspondiente:
  - "Basic Wash" = product_id 'prod_LQjx67EvzQ1PGQ'
  - "Premium Wash" = product_id 'prod_LQjy3uY1m2leN3'
  - "BW/Road Assistance" (mensual) = product_id 'prod_QokBj7SE3bnVgn'
  - "BW/Road Assistance Yearly" = product_id 'prod_TEj2sqBLZUBBby'
  Siempre filtra por product_id (no por nombre) cuando el usuario pregunte por un tier/plan específico."""


def build_user_prompt(schema_prompt: str, existing_segment_names: list[str]) -> str:
    """Port of the template literal built from `schemaPrompt` and `existingSegmentNames`."""
    existing_block = ""
    if existing_segment_names:
        names_list = "\n".join(f'- "{n}"' for n in existing_segment_names)
        existing_block = f"""
IMPORTANTE: Ya existen estos segmentos, NO los repitas ni uses nombres similares:
{names_list}

Debes generar un segmento DIFERENTE y ÚNICO que no exista en la lista anterior.
"""

    return f"""Analiza esta estructura de datos y recomienda un segmento valioso de clientes:

{schema_prompt}

{existing_block}

Basándote en las tablas disponibles, identifica un segmento de clientes que sería valioso para campañas de marketing.
Genera el SQL para obtener los miembros del segmento."""
