"""KPI-module-local config constants.

Deliberately not in app/config.py, which is shared across modules and holds environment-driven
settings — these are fixed deployment facts, the same way chat_bot/config.py keeps its own.
"""

# How long a computed /api/kpis/* payload is reused before BigQuery is queried again. The dashboard
# and analytics pages fire 2-4 queries per client/date-range on every load, and the underlying
# views are rebuilt on a daily schedule, so same-day freshness is enough.
KPI_CACHE_TTL_SECONDS = 12 * 3600
