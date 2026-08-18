"""Chatbot prompts, split by pipeline step.

Step 1 (build_sql_generation_system_prompt): natural-language question -> SQL. Follows the
text-to-SQL best-practice pattern from F:\\replit\\Prompting.md — schema as CREATE TABLE DDL
wrapped in <SQL_SCHEMA>, a <TABLE_GUIDE> mapping business intent to the right table before
the model reads any DDL, and <RULES> for SQL-writing mechanics + verified data-reality
gotchas. This is the prompt sql_agent.py's tool-calling loop actually uses today.

Step 2 (build_answer_generation_system_prompt): query result -> business answer in the
analyst's voice, with <BUSINESS_CONTEXT> instead of a schema. Prompt text is written and
tested standalone (see the bottom of this file), but NOT YET WIRED into sql_agent.py — the
live pipeline still produces its final answer from within the same step-1 tool-calling loop,
not via a separate call to this prompt. Wiring that up (a genuine second LLM call after SQL
execution) is a deliberate follow-up, not done here.

This deployment spans 5 fixed views (only the GCP project differs per BigQuery connection,
force-injected into every tool call's `projectId` argument by sql_agent.py, so it never needs
to appear in the SQL text itself). All 5 column schemas are filled in from live BigQuery
exploration.
"""

CUSTOMER_360_TABLE_ID = "marketing_analytics_ss.customer_360_vw"
DAILY_BUSINESS_METRICS_TABLE_ID = "marketing_analytics_ss.daily_business_metrics_vw"
LOCATION_360_VW_TABLE_ID = "marketing_analytics_ss.location_360_vw"
SESSION_360_VW_TABLE_ID = "marketing_analytics_ss.session_360_vw"
SUBSCRIPTION_360_VW_TABLE_ID = "marketing_analytics_ss.subscription_360_vw"

_CUSTOMER_360_SCHEMA = [
    ("account_id", "STRING", "Unique account identifier from AutoCare."),
    ("account_name", "STRING", "Customer account/business name."),
    ("active_subscriptions", "INT64", "Number of currently active subscriptions."),
    ("address_city", "STRING", "Billing city."),
    ("address_country", "STRING", "Billing country."),
    ("address_line1", "STRING", "Billing address line 1."),
    ("address_line2", "STRING", "Billing address line 2."),
    ("address_postal_code", "STRING", "Billing postal or ZIP code."),
    ("address_state", "STRING", "Billing state or province."),
    ("billing_id", "STRING", "Billing customer identifier mapped to Stripe."),
    ("client_id", "STRING", "Unique client identifier used across AutoCare systems."),
    ("currency", "STRING", "Customer billing currency."),
    ("current_arr", "NUMERIC", "Current Annual Recurring Revenue normalized from subscription amount."),
    ("current_mrr", "NUMERIC", "Current Monthly Recurring Revenue normalized from subscription amount."),
    ("current_period_end", "TIMESTAMP", "Current subscription period end date."),
    ("current_period_start", "TIMESTAMP", "Current subscription period start date."),
    ("current_subscription_amount", "NUMERIC", "Subscription amount in billing currency."),
    ("current_subscription_id", "STRING", "Latest or active subscription identifier."),
    ("current_subscription_status", "STRING", "Current subscription status."),
    ("customer_age_days", "INT64", "Number of days since customer account creation."),
    ("customer_created_date", "TIMESTAMP", "Date the customer was created in AutoCare."),
    ("customer_status", "STRING", "Derived customer lifecycle status (Active Member, Inactive Member, Prospect)."),
    ("days_since_last_visit", "INT64", "Number of days since the customer's most recent visit."),
    ("email", "STRING", "Primary customer email address."),
    ("first_name", "STRING", "Customer first name."),
    ("first_session_date", "TIMESTAMP", "Date of first recorded service session."),
    ("first_subscription_date", "TIMESTAMP", "Date of customer's first subscription."),
    ("full_name", "STRING", "Customer full name."),
    ("has_active_subscription", "BOOL", "TRUE if customer has one or more active subscriptions."),
    ("has_vehicle", "BOOL", "Indicates whether the customer has at least one registered vehicle."),
    ("has_visited", "BOOL", "TRUE if customer has completed at least one service session."),
    ("interval_count", "STRING", "Number of intervals between billing cycles."),
    ("is_payment_delinquent", "BOOL", "Indicates whether the customer has outstanding payment issues."),
    ("last_location_name", "STRING", "Location where the customer was last serviced."),
    ("last_name", "STRING", "Customer last name."),
    ("last_session_date", "TIMESTAMP", "Date of most recent service session."),
    ("latest_subscription_date", "TIMESTAMP", "Date of customer's most recent subscription."),
    ("phone_number", "STRING", "Primary customer phone number."),
    ("plan_id", "STRING", "Stripe plan identifier."),
    ("plan_name", "STRING", "Current subscription plan name."),
    ("product_id", "STRING", "Stripe product identifier."),
    ("refund_required", "STRING", "Whether refund is required for the tier."),
    ("stripe_customer_id", "STRING", "Stripe customer ID."),
    ("subscription_interval", "STRING", "Subscription billing interval (month/year)."),
    ("subscription_tenure_days", "INT64", "Days since customer's first subscription."),
    ("taxable_amount", "STRING", "Taxable amount configured for the membership tier."),
    ("tier_description", "STRING", "Membership tier description."),
    ("tier_key", "STRING", "Internal membership tier key."),
    ("tier_name", "STRING", "Membership tier name."),
    ("tier_order", "STRING", "Membership tier display order."),
    ("tier_perks", "STRING", "Membership benefits and perks."),
    ("total_locations_visited", "INT64", "Number of unique service locations visited."),
    ("total_sessions", "INT64", "Total service sessions completed by the customer."),
    ("total_subscriptions", "INT64", "Total number of subscriptions owned by the customer."),
    ("validation_rules", "STRING", "Validation rules configured for the membership tier."),
    ("vehicle_brands", "ARRAY<STRING>", "List of vehicle brands registered by the customer."),
    ("vehicle_count", "INT64", "Number of vehicles linked to the customer."),
]

_DAILY_BUSINESS_METRICS_SCHEMA = [
    ("account_id", "STRING", "Unique identifier for the customer account."),
    ("account_name", "STRING", "Name of the customer account."),
    ("active_locations_with_sessions", "INT64", "Number of distinct locations with sessions on the business date that are marked as active."),
    ("cancelled_subscriptions", "INT64", "Number of distinct subscriptions cancelled on the business date."),
    ("current_active_subscriptions", "INT64", "Current number of active subscriptions for the account. This is a current snapshot metric and should not be interpreted as historical daily active subscriptions."),
    ("current_arr", "NUMERIC", "Current Annual Recurring Revenue calculated from active monthly and annual subscriptions. This current value is repeated across the business-date spine and should not be interpreted as historical daily ARR."),
    ("current_mrr", "NUMERIC", "Current Monthly Recurring Revenue calculated from active monthly and annual subscriptions. This current value is repeated across the business-date spine and should not be interpreted as historical daily MRR."),
    ("current_total_subscriptions", "INT64", "Current total number of subscriptions for the account. This is a current snapshot metric."),
    ("day_of_week", "INT64", "Day of week number derived from the business date, where Sunday is 1."),
    ("had_cancellations", "BOOL", "TRUE when one or more subscriptions were cancelled on the business date."),
    ("had_new_customers", "BOOL", "TRUE when one or more new customers were created on the business date."),
    ("had_new_subscriptions", "BOOL", "TRUE when one or more subscriptions were created on the business date."),
    ("had_sessions", "BOOL", "TRUE when one or more sessions occurred on the business date."),
    ("locations_with_sessions", "INT64", "Number of distinct locations with at least one session on the business date."),
    ("metric_date", "DATE", "Business date represented by the record. Used as the table partitioning column."),
    ("metric_month", "INT64", "Calendar month number derived from the business date."),
    ("metric_month_name", "STRING", "Year-month representation of the business date in YYYY-MM format."),
    ("metric_quarter", "INT64", "Calendar quarter derived from the business date."),
    ("metric_week", "INT64", "Week number derived from the business date."),
    ("metric_year", "INT64", "Calendar year derived from the business date."),
    ("new_active_subscriptions", "INT64", "Number of newly created subscriptions whose status is active."),
    ("new_customers", "INT64", "Number of distinct customers created on the business date."),
    ("new_subscriptions", "INT64", "Number of distinct subscriptions created on the business date."),
    ("repeat_customers", "INT64", "Number of customers with more than one recorded session who visited on the business date."),
    ("semantic_last_updated", "TIMESTAMP", "Timestamp when the Executive Daily Business Summary semantic layer record was generated or refreshed."),
    ("total_sessions", "INT64", "Total number of distinct sessions recorded on the business date."),
    ("unique_visiting_customers", "INT64", "Number of distinct customers with at least one session on the business date."),
]
_LOCATION_360_SCHEMA = [
    ("account_id", "STRING", ""),
    ("account_name", "STRING", ""),
    ("activity_status", "STRING", ""),
    ("average_sessions_per_customer", "FLOAT64", ""),
    ("customer_visit_days", "INT64", "Number of distinct customer-location visit days, counting each customer once per calendar day."),
    ("days_since_last_session", "INT64", ""),
    ("first_session_date", "TIMESTAMP", ""),
    ("has_activity", "BOOL", ""),
    ("has_new_customers", "BOOL", ""),
    ("has_repeat_customers", "BOOL", ""),
    ("is_operational", "BOOL", ""),
    ("last_session_date", "TIMESTAMP", ""),
    ("location_created_date", "TIMESTAMP", ""),
    ("location_id", "STRING", ""),
    ("location_is_active", "BOOL", ""),
    ("location_name", "STRING", ""),
    ("location_status", "STRING", ""),
    ("new_customers", "INT64", ""),
    ("one_time_customer_rate", "FLOAT64", ""),
    ("one_time_customers", "INT64", ""),
    ("repeat_customer_rate", "FLOAT64", ""),
    ("repeat_customers", "INT64", ""),
    ("semantic_last_updated", "TIMESTAMP", ""),
    ("total_customers", "INT64", ""),
    ("total_sessions", "INT64", ""),
    ("unique_customers", "INT64", ""),
]
_SESSION_360_SCHEMA = [
    ("account_id", "STRING", "Unique identifier for the customer account."),
    ("account_name", "STRING", "Name of the customer account."),
    ("billing_id", "STRING", "Billing customer identifier associated with the client."),
    ("changed_location_since_previous_visit", "BOOL", "Indicates whether the customer visited a different location compared with their previous session."),
    ("client_id", "STRING", "Unique identifier for the customer or client."),
    ("customer_created_date", "TIMESTAMP", "Date when the customer account was created."),
    ("days_since_previous_visit", "INT64", "Number of days between the current session and the customer's previous session."),
    ("email", "STRING", "Customer email address."),
    ("first_name", "STRING", "Customer first name."),
    ("full_name", "STRING", "Customer full name constructed from first name and last name."),
    ("is_at_active_location", "BOOL", "Indicates whether the session occurred at a currently active service location."),
    ("is_first_visit", "BOOL", "Indicates whether the session is the customer's first recorded visit."),
    ("is_repeat_visit", "BOOL", "Indicates whether the customer has visited previously."),
    ("last_name", "STRING", "Customer last name."),
    ("location_created_date", "TIMESTAMP", "Date when the service location was created."),
    ("location_id", "STRING", "Unique identifier of the service location where the session occurred."),
    ("location_is_active", "BOOL", "Indicates whether the service location is currently active."),
    ("location_name", "STRING", "Name of the service location where the session occurred."),
    ("phone_number", "STRING", "Customer phone number."),
    ("previous_location_id", "STRING", "Location identifier of the customer's immediately preceding session."),
    ("previous_location_name", "STRING", "Location name of the customer's immediately preceding session."),
    ("previous_session_date", "TIMESTAMP", "Date and time of the customer's immediately preceding session."),
    ("semantic_last_updated", "TIMESTAMP", "Timestamp when the Session 360 semantic layer record was generated or refreshed."),
    ("session_date", "TIMESTAMP", "Date and time when the customer session occurred."),
    ("session_date_date", "DATE", "Calendar date of the customer session, derived from session_date and used for date-based analysis."),
    ("session_description", "STRING", "Description or details of the customer session."),
    ("session_id", "STRING", "Unique identifier for the customer service session."),
    ("session_status", "STRING", "Current status of the session based on session date: Future, Today, Completed, or Unknown."),
    ("session_type", "STRING", "Type or category of the customer session."),
    ("source_insert_dttm", "TIMESTAMP", "Timestamp when the source session record was inserted into the source system."),
    ("visit_number", "INT64", "Sequential visit number for the customer based on chronological session history."),
]
_SUBSCRIPTION_360_SCHEMA = [
    ("account_id", "STRING", "Unique AutoCare account identifier."),
    ("account_name", "STRING", "Customer account or business name."),
    ("address_city", "STRING", "Billing city."),
    ("address_country", "STRING", "Billing country."),
    ("address_line1", "STRING", "Billing address line 1."),
    ("address_line2", "STRING", "Billing address line 2."),
    ("address_postal_code", "STRING", "Billing postal or ZIP code."),
    ("address_state", "STRING", "Billing state or province."),
    ("billing_id", "STRING", "Billing identifier linked to Stripe."),
    ("canceled_at", "TIMESTAMP", "Timestamp when the subscription was cancelled."),
    ("client_id", "STRING", "Unique AutoCare client identifier."),
    ("collection_method", "STRING", "Subscription payment collection method."),
    ("currency", "STRING", "Subscription billing currency."),
    ("current_arr", "NUMERIC", "Annual Recurring Revenue normalized from the subscription amount."),
    ("current_mrr", "NUMERIC", "Monthly Recurring Revenue normalized from the subscription amount."),
    ("current_period_end", "TIMESTAMP", "Current billing period end timestamp."),
    ("current_period_start", "TIMESTAMP", "Current billing period start timestamp."),
    ("customer_created_date", "TIMESTAMP", "Date customer account was created."),
    ("customer_name", "STRING", "Customer full name."),
    ("days_until_renewal", "INT64", "Remaining days until the current subscription renews."),
    ("email", "STRING", "Primary customer email address."),
    ("ended_at", "TIMESTAMP", "Timestamp when the subscription ended."),
    ("interval_count", "INT64", "Number of billing intervals between renewals."),
    ("is_active_subscription", "BOOL", "TRUE if the subscription is currently active."),
    ("is_auto_charge", "BOOL", "TRUE if payments are collected automatically."),
    ("is_cancelled_subscription", "BOOL", "TRUE if the subscription has been cancelled."),
    ("is_expired_subscription", "BOOL", "TRUE if the subscription period has already expired."),
    ("is_payment_delinquent", "BOOL", "Indicates whether the customer has overdue payments."),
    ("is_trial_subscription", "BOOL", "TRUE if the subscription is in a trial period."),
    ("phone_number", "STRING", "Customer phone number."),
    ("plan_id", "STRING", "Stripe plan identifier."),
    ("plan_name", "STRING", "Stripe subscription plan name."),
    ("product_id", "STRING", "Stripe product identifier."),
    ("refund_required", "STRING", "Indicates whether a refund is required for the tier."),
    ("renewal_bucket", "STRING", "Bucket indicating how soon the subscription will renew."),
    ("renewal_due_next_30_days", "BOOL", "TRUE if the subscription is due to renew within the next 30 days."),
    ("semantic_last_updated", "TIMESTAMP", "Timestamp when the semantic record was last generated."),
    ("stripe_customer_id", "STRING", "Stripe customer identifier."),
    ("subscription_age_bucket", "STRING", "Subscription tenure grouped into age ranges."),
    ("subscription_age_days", "INT64", "Number of days since the subscription was created."),
    ("subscription_amount", "NUMERIC", "Recurring subscription amount in billing currency."),
    ("subscription_created_at", "TIMESTAMP", "Date and time the subscription was created."),
    ("subscription_id", "STRING", "Unique Stripe subscription identifier."),
    ("subscription_interval", "STRING", "Subscription billing interval (monthly or yearly)."),
    ("subscription_lifecycle", "STRING", "Derived subscription lifecycle category."),
    ("subscription_status", "STRING", "Current Stripe subscription status."),
    ("taxable_amount", "STRING", "Taxable amount defined for the tier."),
    ("tier_description", "STRING", "Description of the membership tier."),
    ("tier_key", "STRING", "Internal tier key."),
    ("tier_name", "STRING", "Membership tier name."),
    ("tier_order", "STRING", "Display order of the membership tier."),
    ("tier_perks", "STRING", "Benefits and perks associated with the tier."),
    ("validation_description", "STRING", "Description of membership validation requirements."),
    ("validation_rules", "STRING", "Validation rules configured for the tier."),
]

# (table_id, schema, grain_description) triples, in the order they're rendered into
# <SQL_SCHEMA>. grain_description is a one-line "what's one row here, and is the obvious key
# actually unique" note, verified live against real BigQuery data (2026-08-18) rather than
# assumed from column names — see the row-counting gotchas in <RULES> for the two tables
# where the obvious key ISN'T reliably unique.
_ALL_TABLES = [
    (CUSTOMER_360_TABLE_ID, _CUSTOMER_360_SCHEMA, "One row per customer — client_id is unique here."),
    (
        DAILY_BUSINESS_METRICS_TABLE_ID,
        _DAILY_BUSINESS_METRICS_SCHEMA,
        "Daily-grain, business-wide aggregate — one row per metric_date, but see the "
        "account_id-IS-NULL gotcha in RULES before aggregating.",
    ),
    (LOCATION_360_VW_TABLE_ID, _LOCATION_360_SCHEMA, "One row per physical service location — location_id is unique here."),
    (SESSION_360_VW_TABLE_ID, _SESSION_360_SCHEMA, "One row per individual customer service session — session_id is unique here."),
    (
        SUBSCRIPTION_360_VW_TABLE_ID,
        _SUBSCRIPTION_360_SCHEMA,
        "One row per subscription, EXCEPT subscription_id is not always unique — see the "
        "duplicate-row gotcha in RULES before counting subscriptions.",
    ),
]


def _table_as_ddl(table_id: str, schema: list[tuple[str, str, str]], grain_description: str) -> str:
    """Renders one table's schema as a CREATE TABLE statement with one inline comment per
    column, per the article's #3/#4 guidance (DDL is the format the model has seen the most
    of in its own training data for describing tables; comments carry the human
    description), plus a leading one-line grain comment. Tables with no schema filled in yet
    render as a TODO placeholder block instead of guessing columns."""
    if not schema:
        return f"-- {grain_description}\nCREATE TABLE `{table_id}` (\n  -- TODO: schema not filled in yet\n);"

    def _column_line(name: str, dtype: str, desc: str) -> str:
        return f"  {name} {dtype} -- {desc}" if desc else f"  {name} {dtype}"

    column_lines = ",\n".join(_column_line(name, dtype, desc) for name, dtype, desc in schema)
    return f"-- {grain_description}\nCREATE TABLE `{table_id}` (\n{column_lines}\n);"


_SQL_SCHEMA_BLOCK = "\n\n".join(
    _table_as_ddl(table_id, schema, grain_description) for table_id, schema, grain_description in _ALL_TABLES
)

# ---------------------------------------------------------------------------
# Step 1: natural-language question -> SQL (the only step this file covers so far).
# Structure follows F:\replit\Prompting.md's recommended template: <USER_PROMPT> holding the
# live question, then each table as CREATE TABLE DDL inside a single <SQL_SCHEMA> tag, then
# minimal surrounding narrative. Rebuilt fresh per request (not a prompt fixed once at
# import time) — build_sql_generation_system_prompt() interpolates the CURRENT turn's
# question into <USER_PROMPT> every time sql_agent.py's _build_initial_messages() starts a
# new question, matching the article's one-shot template shape exactly. Only that new
# question goes here; prior conversation turns are still threaded as ordinary chat
# user/assistant messages after this system message, same as before.
#
# <TABLE_GUIDE> answers the question that actually decides correctness before any SQL is
# written: which table(s) does THIS business question even need? Reading 5 CREATE TABLE
# blocks and guessing from column names is exactly how a previous live trace answered a
# completely different, unrelated question with no query at all (asked about "purchases in
# the last 3 days", answered about "most locations visited" — neither table nor intent
# matched). This section exists to stop that at the source: map business language to a
# table BEFORE touching <SQL_SCHEMA>.
#
# <RULES> currently holds only SQL-writing mechanics (how to handle equality/matching, NULLs,
# joins). The larger domain/business rules (anti-fabrication, "last N days" vs "last N items"
# disambiguation, entity-existence validation, timestamp handling, vague-term definitions,
# etc.) are being redesigned separately and will be layered in on a follow-up pass, not
# carried over from the old prompt as-is.
# ---------------------------------------------------------------------------

_TABLE_GUIDE = """- Question about a CUSTOMER as a person/account (who are they, what tier/plan, current MRR,
  engagement recency, "list/find customers where...") -> customer_360_vw. One row per customer;
  this is the default table for anything framed around "a customer" or "customers".
- Question about a TREND OVER TIME at the whole-business level (sessions per day/week/month,
  new customers over time, MRR/cancellations over time, day-of-week patterns) -> use
  daily_business_metrics_vw. This table has no per-customer or per-location key — it cannot
  answer "which customer" or "which location" questions, only business-wide totals per date.
- Question about a LOCATION (which location has the most customers/sessions, comparing
  locations, a location's status) -> location_360_vw. Only 11 rows, one per physical location.
- Question about an individual VISIT or SESSION EVENT (did a customer visit recently, how many
  sessions in a period, first-time vs repeat visits, which location a visit happened at) ->
  session_360_vw. This is the closest table to a "purchase"/"visit" event log — there is no
  literal purchase/transaction table, so "purchased" or "visited" in a question should usually
  map here via session_date, unless the question is really about billing (see subscription_360_vw).
- Question about a SUBSCRIPTION as its own entity (plan/tier details, renewal timing, when it
  was created/cancelled, refund status, subscription age) -> subscription_360_vw. Unlike
  customer_360_vw's single "current subscription" snapshot columns, this table can have multiple
  rows per customer (full subscription history) — use it when the question needs subscription
  history/detail, not just a customer's current plan.
- If a question could plausibly map to more than one table (e.g. "recent activity" could mean
  sessions or subscription changes), pick the interpretation that matches the literal words used
  (visit/session -> session_360_vw, subscription/plan/billing -> subscription_360_vw) and state
  which one you used in your answer rather than silently picking one."""

_SQL_GENERATION_TEMPLATE = """You're an expert at SQL, working inside a BigQuery tool-calling agent. You will be
given a business user's natural-language question about their own customer data, and a set of
table definitions. Write a single BigQuery SQL SELECT statement that answers the question, then
call the SQL-execution tool with that query.

<USER_PROMPT>
{user_prompt}
</USER_PROMPT>

<TABLE_GUIDE>
{table_guide}
</TABLE_GUIDE>

<SQL_SCHEMA>
{schema}
</SQL_SCHEMA>

<RULES>
- OUT OF SCOPE / NOT CONFIDENT: If the question doesn't clearly map to any table in TABLE_GUIDE,
  or you aren't confident you can write a correct query for it, do NOT guess, do NOT call the
  SQL tool with a speculative query, and do NOT answer a different or adjacent question instead.
  Respond in plain text telling the user this is outside what you can answer with the available
  data — e.g. "I don't have data to answer that" / "that's outside what this dataset covers" —
  rather than fabricating an unrelated answer. This is the ONLY case where skipping the SQL tool
  and answering directly is acceptable, besides a genuine advice/recommendation question that
  doesn't need data at all.
- STRIPE VS AUTOCARE TIER NAMING (verified against live data): plan_name and product_id are
  ALWAYS identical — plan_name is just Stripe's raw product id (e.g. "prod_LQjx67EvzQ1PGQ"), not
  a human name. NEVER filter or answer using plan_name/product_id for a tier the user names in
  words — use tier_name, the AutoCare-facing name, instead. The verified crosswalk is:
  product_id 'prod_LQjx67EvzQ1PGQ' / tier_key 'pro' -> tier_name 'Unlimited Premium Wash';
  product_id 'prod_LQjy3uY1m2leN3' / tier_key 'basic' -> tier_name 'Unlimited Basic Wash';
  product_id 'prod_QokBj7SE3bnVgn' / tier_key 'connect' -> tier_name 'Unlimited Basic Wash and
  Road Assistance'; product_id 'prod_TEj2sqBLZUBBby' / tier_key 'connect' -> tier_name 'Unlimited
  Basic Wash and Road Assistance Monthly'. Note tier_key 'connect' maps to TWO different
  tier_names (the base plan and its Monthly variant) — tier_key alone can't disambiguate them, so
  if a user says "Connect" without specifying which, filter on tier_name (LIKE '%Road
  Assistance%') to match both rather than guessing one, or ask which. If a user says "Pro" or
  "Premium", that means tier_name 'Unlimited Premium Wash'; "Basic" means 'Unlimited Basic Wash'.
- STRING EQUALITY: Never use exact `=` to filter a free-text/string column against a
  user-provided name, label, or keyword — casing and spelling in the data won't reliably match
  what the user typed. Use `LOWER(col) LIKE LOWER('%term%')` (or `REGEXP_CONTAINS`) instead.
  Example: instead of `WHERE tier_name = 'Gold'`, use `WHERE LOWER(tier_name) LIKE '%gold%'`.
- ENUM-LIKE STRING COLUMNS: Columns with a small, fixed set of known values (e.g.
  `subscription_status`, `session_status`, `activity_status`) may be compared with `=` once the
  value is confirmed to be one of the known values, but still normalize case:
  `LOWER(col) = LOWER('active')` rather than a bare `=`.
- NON-STRING EQUALITY: Exact `=`/`!=` is correct and expected for IDs, booleans, numbers, and
  date/timestamp comparisons — the fuzzy-match rule above applies only to free-text string
  filters, not typed values.
- NULL-SAFE FILTERING: `=`, `!=`, and `<>` never match a NULL value, in either direction. When a
  filter is meant to include rows where a column is NULL (e.g. "never happened" / "no value
  recorded" cases), add it explicitly: `(col > 60 OR col IS NULL)`, not just `col > 60`.
- JOINING ACROSS TABLES: `account_id` is a fixed tenant identifier and is IDENTICAL on every row
  in every table — never join on it, it matches everything and filters nothing. Use the real
  per-entity keys instead: `client_id` links customer_360_vw, session_360_vw, and
  subscription_360_vw at the customer grain (subscription_360_vw.client_id can be NULL — a
  subscription with no linked customer). `location_id` links location_360_vw and session_360_vw
  at the location grain. daily_business_metrics_vw has no customer or location key at all — it's
  a business-wide daily aggregate (keyed only by `metric_date`) and cannot be joined to the other
  4 tables at customer or location grain.
- Prefer the read-only SQL-execution tool; do not attempt to write or modify data unless the
  user explicitly asks for it.
- ROW-COUNTING GOTCHAS (verified against live data, not assumed): subscription_360_vw has exact
  duplicate rows for some subscriptions — always `COUNT(DISTINCT subscription_id)`, never
  `COUNT(*)`, when counting subscriptions. daily_business_metrics_vw has a second, all-zero
  placeholder row with `account_id IS NULL` for a large share of business dates — always add
  `WHERE account_id IS NOT NULL` before aggregating daily metrics, or totals will be
  understated/rows double-counted.
- refund_required (subscription_360_vw) is a STRING holding the literal text 'true'/'false', not
  a BOOL — filter with `refund_required = 'true'`, not a boolean comparison.
- SUBSCRIPTION STATUS IS STALE, NOT LIVE (verified against live data): `subscription_status =
  'active'` and `is_active_subscription = TRUE` (the latter is just a direct copy of the former,
  not an independent check) do NOT reliably mean the subscription is currently in a paid period —
  37% of rows marked 'active' already have `current_period_end` in the past /
  `days_until_renewal` negative, meaning the status field isn't kept in sync once a period lapses.
  A smaller number of 'canceled' rows show the opposite: a `current_period_end` still in the
  future. For any "currently active" / "paying right now" question, do NOT rely on
  subscription_status alone — check `current_period_end >= CURRENT_TIMESTAMP()` (or
  `days_until_renewal >= 0`) too, and say plainly which definition you used if the two disagree.
</RULES>

Do NOT prefix any table name with a project id in your SQL — the correct GCP project is already
applied automatically via the `projectId` argument that's pre-filled on every tool call. Just
reference each table as shown in <SQL_SCHEMA> (backtick-quoted, dataset.table form) in
FROM/JOIN clauses."""


def build_sql_generation_system_prompt(user_message: str) -> str:
    """Rebuilds the system prompt fresh for the current turn, embedding the live question in
    <USER_PROMPT> at the top of the prompt, above <TABLE_GUIDE> and <SQL_SCHEMA> — the
    article's template shape, extended with a table-selection guide so the model picks the
    right table from business intent before it ever reads the column-level DDL. Called once
    per new user question in sql_agent.py's _build_initial_messages(), not cached at import
    time, since the question changes every call."""
    return _SQL_GENERATION_TEMPLATE.format(
        user_prompt=user_message, table_guide=_TABLE_GUIDE, schema=_SQL_SCHEMA_BLOCK
    )


# ---------------------------------------------------------------------------
# Step 2: query result -> business answer. Same <TAG> template shape as step 1, but there's
# no schema to describe here — <SQL_SCHEMA> is replaced with <BUSINESS_CONTEXT> (what
# AutoCare/this data actually represents, in plain business terms) and a new <QUERY_RESULT>
# slot holds the SQL + rows that came back, so the model answers strictly from what was
# actually retrieved rather than the schema alone.
# ---------------------------------------------------------------------------

_BUSINESS_CONTEXT = """AutoCare is a car wash membership CRM. Customers sign up and visit AutoCare's physical wash
locations for service sessions; their membership is billed on a recurring subscription through Stripe. So there
are three things every question is really about: the CUSTOMER (their identity, tier, and engagement), the
SESSION (an actual visit to a location), and the SUBSCRIPTION (the Stripe-billed membership that funds it) — plus
LOCATION (where sessions happen) and business-wide DAILY METRICS (trends across all of the above). The data you're
given below already reflects a query that was run against this business's live BigQuery data on the user's behalf —
you are not guessing at what exists, you are reporting what was actually found."""

_ANSWER_GENERATION_TEMPLATE = """You are a senior data analyst at a marketing analytics platform, reporting a finding back to
the business user who asked the question below. A query has already been run against their data on your behalf —
your job now is to turn the result into an answer a person would actually want to read: direct, correct, and useful
for a decision, not a database echoing rows back.

<USER_PROMPT>
{user_prompt}
</USER_PROMPT>

<BUSINESS_CONTEXT>
{business_context}
</BUSINESS_CONTEXT>

<QUERY_RESULT>
{query_result}
</QUERY_RESULT>

<RULES>
- Answer like a senior data analyst, not a database: lead with the direct answer to what was asked, then add the
  "so what" — what stands out, what's above/below expectation, and what it implies for this customer, segment, or
  location. Prefer specific, named findings over generic statements.
- Ground every fact, name, and number strictly in <QUERY_RESULT> as given — never state a number, date, or name
  that isn't actually in these rows. If the result is empty, say plainly that nothing matched; never invent an
  illustrative or "example" row to fill the gap, even with a disclaimer.
- Use business-friendly language and round numbers sensibly (e.g. "$1.2K MRR", not "1247.389999999998"). Never
  expose raw column names, table names, or SQL to the user — translate into plain business terms.
- PLAIN TEXT ONLY — the chat UI renders this as raw text with no markdown support. NEVER use **bold**, _italic_,
  markdown headers (#), or numbered/bulleted list syntax. Write lists as plain sentences or comma/semicolon-
  separated clauses instead.
- Tables and charts are rendered automatically by the application straight from the query result, using the same
  data you were given — you do not need to describe, format, mention, or refer to a chart/table in your text ("see
  the chart below" etc.); just write the narrative answer, the visualization is handled separately.
- If the question was really a request for advice or recommendations rather than data, answer from general
  marketing/customer-success best practice grounded in whatever data is available — not every recommendation needs
  to cite a specific number.
</RULES>"""


def format_query_result_block(sql: str, columns: list[str], rows: list[dict], total_rows: int, truncated: bool) -> str:
    """Renders the SQL + returned rows into the <QUERY_RESULT> slot. Given to the model for
    context (so it understands what was actually queried), not shown to the end user — RULES
    above tells the model not to repeat the SQL/column names verbatim in its answer."""
    rows_text = "\n".join(", ".join(f"{col}={row.get(col)}" for col in columns) for row in rows) or "(no rows)"
    truncated_note = f" (showing {len(rows)} of {total_rows} total rows)" if truncated else ""
    return f"SQL executed:\n{sql}\n\nColumns: {', '.join(columns)}\n\nRows{truncated_note}:\n{rows_text}"


def build_answer_generation_system_prompt(user_message: str, query_result_block: str) -> str:
    """Rebuilds the answer-generation system prompt fresh per turn, same as
    build_sql_generation_system_prompt — the question and the query result both change every
    call, so nothing here is cached at import time."""
    return _ANSWER_GENERATION_TEMPLATE.format(
        user_prompt=user_message, business_context=_BUSINESS_CONTEXT, query_result=query_result_block
    )
