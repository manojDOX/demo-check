"""GoHighLevel CRM export module.

Port of the `/api/exports`, `/api/ghl/*`, and `/api/webhooks/new-customers`
handlers in server/routes.ts. There is no dedicated GHL service file in the
Node backend (server/services/ has no ghl helper) — all logic lives inline
in routes.ts, so it's ported here + client.py the same way.

Credential resolution: the Node backend (and this port) use ONLY the
platform-level `GHL_API_KEY` / `GHL_LOCATION_ID` env vars (`app.config`
settings) — there is no per-user override lookup anywhere in routes.ts or
storage.ts, despite `User.ghl_api_key` / `User.ghl_location_id` columns
existing on the model.
"""

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.serialize import to_camel, to_camel_list
from app.db import SessionLocal, get_db
from app.dependencies import get_user_id, is_admin_user, require_authenticated_or_token
from app.modules.ghl import client as ghl_client
from app.modules.ghl import repo as ghl_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ghl"])

# GHL allows ~100 requests/minute -> ~650ms between requests.
GHL_RATE_LIMIT_DELAY_SECONDS = 0.65
MAX_BATCH_SIZE = 10000
MAX_ERRORS_SEND_CONTACTS = 5
MAX_ERRORS_WEBHOOK = 10


# ============================================================
# Exports history
# ============================================================


@router.get("/api/exports")
async def list_exports(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    try:
        user_id = get_user_id(request)
        exports = await ghl_repo.get_exports(db, user_id)
        return to_camel_list(exports)
    except Exception:
        logger.exception("Error fetching exports")
        raise HTTPException(status_code=500, detail="Failed to fetch exports")


class CreateExportRequest(BaseModel):
    segmentId: int | None = None
    ghlLocationId: str | None = None
    ghlTags: list[str] | None = None


async def _complete_export_after_delay(export_id: int, delay_seconds: float) -> None:
    """Port of the Node handler's `setTimeout(..., 3000)` that flips a newly
    created export from "processing" to "completed" after a simulated delay.
    Runs as a detached background task against its own DB session, since the
    request-scoped session is closed by the time this fires."""
    await asyncio.sleep(delay_seconds)
    try:
        async with SessionLocal() as session:
            await ghl_repo.update_export(
                session,
                export_id,
                {"status": "completed", "completed_at": datetime.now(timezone.utc).replace(tzinfo=None)},
            )
    except Exception:
        logger.exception("Error completing export %s", export_id)


@router.post("/api/exports")
async def create_export(
    body: CreateExportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    try:
        user_id = get_user_id(request)
        if not await is_admin_user(request, db):
            raise HTTPException(status_code=403, detail="Admin access required")

        segment = await ghl_repo.get_segment(db, body.segmentId) if body.segmentId is not None else None
        contact_count = (
            segment.contact_count if segment and segment.contact_count else random.randint(100, 1099)
        )

        ghl_export = await ghl_repo.create_export(
            db,
            user_id=user_id,
            segment_id=body.segmentId,
            contact_count=contact_count,
            status="processing",
            ghl_location_id=body.ghlLocationId,
            ghl_tags=body.ghlTags,
        )

        asyncio.create_task(_complete_export_after_delay(ghl_export.id, 3.0))

        return to_camel(ghl_export)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error creating export")
        raise HTTPException(status_code=500, detail="Failed to create export")


# ============================================================
# GoHighLevel Settings & Contact Sync
# ============================================================


@router.get("/api/ghl/settings")
async def get_ghl_settings(_=Depends(require_authenticated_or_token)):
    try:
        settings = get_settings()
        ghl_api_key = settings.GHL_API_KEY or None
        ghl_location_id = settings.GHL_LOCATION_ID or None
        return {
            "ghlApiKey": ("•" * 8 + ghl_api_key[-4:]) if ghl_api_key else None,
            "ghlLocationId": ghl_location_id,
            "isConfigured": bool(ghl_api_key and ghl_location_id),
        }
    except Exception:
        logger.exception("Error fetching GHL settings")
        raise HTTPException(status_code=500, detail="Failed to fetch GHL settings")


@router.post("/api/ghl/send-contacts")
async def send_contacts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    body: dict[str, Any] = Body(...),
    _=Depends(require_authenticated_or_token),
):
    try:
        user_id = get_user_id(request)
        if not await is_admin_user(request, db):
            raise HTTPException(status_code=403, detail="Admin access required")

        settings = get_settings()
        ghl_api_key = settings.GHL_API_KEY or None
        ghl_location_id = settings.GHL_LOCATION_ID or None

        if not ghl_api_key or not ghl_location_id:
            raise HTTPException(
                status_code=400,
                detail="GoHighLevel is not configured. Please contact your administrator.",
            )

        contacts = body.get("contacts")
        tags = body.get("tags")
        segment_id = body.get("segmentId")

        if not contacts or not isinstance(contacts, list) or len(contacts) == 0:
            raise HTTPException(status_code=400, detail="No contacts provided")

        if len(contacts) > MAX_BATCH_SIZE:
            raise HTTPException(status_code=400, detail="Maximum 10,000 contacts per batch")

        results: dict[str, Any] = {
            "total": len(contacts),
            "created": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }

        for contact in contacts:
            try:
                ghl_contact = ghl_client.build_contact_payload_for_export(contact, tags)
                if ghl_contact is None:
                    results["failed"] += 1
                    continue

                response = await ghl_client.upsert_contact(ghl_api_key, ghl_location_id, ghl_contact)

                if response.is_success:
                    data = response.json() if response.content else {}
                    if isinstance(data, dict) and (data.get("contact") or {}).get("id"):
                        results["created"] += 1
                    else:
                        results["updated"] += 1
                else:
                    try:
                        error_data = response.json()
                    except Exception:
                        error_data = {}
                    results["failed"] += 1
                    if len(results["errors"]) < MAX_ERRORS_SEND_CONTACTS:
                        who = contact.get("email") or contact.get("name") or "unknown"
                        message = (error_data or {}).get("message") or response.reason_phrase
                        results["errors"].append(f"Contact {who}: {message}")

                await asyncio.sleep(GHL_RATE_LIMIT_DELAY_SECONDS)
            except Exception as err:
                results["failed"] += 1
                if len(results["errors"]) < MAX_ERRORS_SEND_CONTACTS:
                    results["errors"].append(str(err) or "Unknown error")

        if segment_id:
            await ghl_repo.create_export(
                db,
                user_id=user_id,
                segment_id=segment_id,
                contact_count=results["created"] + results["updated"],
                status="completed" if results["failed"] == 0 else "partial",
                ghl_location_id=ghl_location_id,
                ghl_tags=tags or [],
            )

        return results
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Error sending contacts to GHL")
        raise HTTPException(status_code=500, detail=str(error) or "Failed to send contacts")


# ============================================================
# Webhook Receiver - Incoming customers from BigQuery
# ============================================================


@router.post("/api/webhooks/new-customers")
async def webhook_new_customers(request: Request, body: dict[str, Any] = Body(default={})):
    try:
        settings = get_settings()
        webhook_secret = settings.WEBHOOK_SECRET or None
        if webhook_secret:
            auth_header = request.headers.get("x-webhook-secret") or request.headers.get("authorization")
            provided_secret = auth_header.replace("Bearer ", "") if isinstance(auth_header, str) else ""
            if provided_secret != webhook_secret:
                raise HTTPException(status_code=401, detail="Unauthorized: invalid webhook secret")

        ghl_api_key = settings.GHL_API_KEY or None
        ghl_location_id = settings.GHL_LOCATION_ID or None

        if not ghl_api_key or not ghl_location_id:
            raise HTTPException(status_code=500, detail="GoHighLevel is not configured on this server")

        customers = body.get("customers")
        customer_list = customers if customers is not None else ([body["customer"]] if body.get("customer") else None)

        if not customer_list or not isinstance(customer_list, list) or len(customer_list) == 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "No customers provided. Send { customers: [...] } or { customer: {...} }",
                    "expected_format": {
                        "customers": [
                            {
                                "customer_id": "cus_123",
                                "email": "john@example.com",
                                "name": "John Doe",
                                "phone": "+1234567890",
                                "product_id": "prod_LQjx67EvzQ1PGQ",
                            }
                        ],
                        "tags": ["New Customer"],
                    },
                },
            )

        if len(customer_list) > MAX_BATCH_SIZE:
            raise HTTPException(status_code=400, detail="Maximum 10,000 customers per request")

        tags = body.get("tags")

        logger.info("[Webhook] Received %d customer(s) from BigQuery", len(customer_list))

        results: dict[str, Any] = {
            "total": len(customer_list),
            "created": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        for contact in customer_list:
            try:
                ghl_contact = ghl_client.build_contact_payload_for_webhook(contact, tags)
                if ghl_contact is None:
                    results["failed"] += 1
                    if len(results["errors"]) < MAX_ERRORS_WEBHOOK:
                        who = contact.get("customer_id") or "unknown"
                        results["errors"].append(f"Contact {who} skipped: no email, phone, or name")
                    continue

                response = await ghl_client.upsert_contact(ghl_api_key, ghl_location_id, ghl_contact)

                if response.is_success:
                    data = response.json() if response.content else {}
                    if isinstance(data, dict) and (data.get("contact") or {}).get("id"):
                        results["created"] += 1
                    else:
                        results["updated"] += 1
                else:
                    try:
                        error_data = response.json()
                    except Exception:
                        error_data = {}
                    results["failed"] += 1
                    if len(results["errors"]) < MAX_ERRORS_WEBHOOK:
                        who = contact.get("email") or contact.get("name") or "unknown"
                        message = (error_data or {}).get("message") or response.reason_phrase
                        results["errors"].append(f"Contact {who}: {message}")

                await asyncio.sleep(GHL_RATE_LIMIT_DELAY_SECONDS)
            except Exception as err:
                results["failed"] += 1
                if len(results["errors"]) < MAX_ERRORS_WEBHOOK:
                    results["errors"].append(str(err) or "Unknown error")

        logger.info(
            "[Webhook] Finished: %d created, %d updated, %d failed",
            results["created"],
            results["updated"],
            results["failed"],
        )

        return results
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("[Webhook] Error processing incoming customers")
        raise HTTPException(status_code=500, detail=str(error) or "Failed to process incoming customers")
