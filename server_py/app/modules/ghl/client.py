"""Thin HTTP client for the GoHighLevel (LeadConnector) REST API.

Port of the inline `fetch(...)` calls in server/routes.ts's
`/api/ghl/send-contacts` and `/api/webhooks/new-customers` handlers.
Both handlers POST to the same `contacts/` upsert endpoint with the same
headers, so that call is centralized here; the business logic for building
the contact payload and interpreting the response stays in router.py to
mirror the two call sites' (slightly different) TS logic exactly.
"""

from typing import Any

import httpx

GHL_CONTACTS_URL = "https://services.leadconnectorhq.com/contacts/"
GHL_API_VERSION = "2021-07-28"

# Port of the `productMap` used by the `/api/webhooks/new-customers` handler
# in server/routes.ts to translate Stripe-style product ids into tag names.
PRODUCT_MAP = {
    "prod_LQjx67EvzQ1PGQ": "Basic Wash",
    "prod_LQjy3uY1m2leN3": "Premium Wash",
    "prod_QokBj7SE3bnVgn": "BW/Road Assistance",
    "prod_TEj2sqBLZUBBby": "BW/Road Assistance Yearly",
}


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first, last


def build_contact_payload_for_export(
    contact: dict[str, Any], tags: list[str] | None
) -> dict[str, Any] | None:
    """Port of the `ghlContact` construction in `/api/ghl/send-contacts`.
    Returns None if the contact has none of email/phone/firstName (skip)."""
    ghl_contact: dict[str, Any] = {}

    name = contact.get("name")
    if name:
        first, last = _split_name(str(name))
        ghl_contact["firstName"] = first
        ghl_contact["lastName"] = last
    if contact.get("firstName"):
        ghl_contact["firstName"] = contact["firstName"]
    if contact.get("lastName"):
        ghl_contact["lastName"] = contact["lastName"]
    if contact.get("email"):
        ghl_contact["email"] = contact["email"]
    if contact.get("phone"):
        ghl_contact["phone"] = contact["phone"]
    if tags and isinstance(tags, list) and len(tags) > 0:
        ghl_contact["tags"] = tags

    if not ghl_contact.get("email") and not ghl_contact.get("phone") and not ghl_contact.get("firstName"):
        return None
    return ghl_contact


def build_contact_payload_for_webhook(
    contact: dict[str, Any], tags: list[str] | None
) -> dict[str, Any] | None:
    """Port of the `ghlContact` construction in `/api/webhooks/new-customers`.
    Returns None if the contact has none of email/phone/firstName (skip)."""
    ghl_contact: dict[str, Any] = {}

    name = contact.get("name")
    if name:
        first, last = _split_name(str(name))
        ghl_contact["firstName"] = first
        ghl_contact["lastName"] = last
    if contact.get("firstName") or contact.get("first_name"):
        ghl_contact["firstName"] = contact.get("firstName") or contact.get("first_name")
    if contact.get("lastName") or contact.get("last_name"):
        ghl_contact["lastName"] = contact.get("lastName") or contact.get("last_name")
    if contact.get("email"):
        ghl_contact["email"] = contact["email"]
    if contact.get("phone"):
        ghl_contact["phone"] = contact["phone"]

    contact_tags: list[str] = []
    if tags and isinstance(tags, list) and len(tags) > 0:
        contact_tags.extend(tags)
    product_id = contact.get("product_id")
    if product_id:
        contact_tags.append(PRODUCT_MAP.get(product_id, product_id))
    if contact.get("tags") and isinstance(contact["tags"], list):
        contact_tags.extend(contact["tags"])
    if contact_tags:
        ghl_contact["tags"] = contact_tags

    if not ghl_contact.get("email") and not ghl_contact.get("phone") and not ghl_contact.get("firstName"):
        return None
    return ghl_contact


async def upsert_contact(
    api_key: str, location_id: str, contact_payload: dict[str, Any]
) -> httpx.Response:
    """POST a contact to GoHighLevel. Mirrors the TS `fetch` call exactly:
    same URL, headers, and body shape (`{...ghlContact, locationId}`)."""
    async with httpx.AsyncClient() as client:
        return await client.post(
            GHL_CONTACTS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Version": GHL_API_VERSION,
            },
            json={**contact_payload, "locationId": location_id},
        )
