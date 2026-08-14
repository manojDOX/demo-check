from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import to_camel, to_camel_list
from app.db import get_db
from app.dependencies import (
    can_access_client,
    get_user_id,
    is_admin_user,
    require_authenticated_or_token,
)
from app.modules.clients import repo
from app.modules.team import repo as team_repo

router = APIRouter(tags=["clients"])


# ============================================================
# Clients (with collaborator access control)
# ============================================================


@router.get("/api/clients")
async def list_clients(
    request: Request, db: AsyncSession = Depends(get_db), _=Depends(require_authenticated_or_token)
):
    token_session = request.state.session.get("tokenAuth")
    if token_session:
        assigned = await team_repo.get_team_member_clients(db, token_session["teamMemberId"])
        client_ids = {ac.client_id for ac in assigned}
        admin_clients = await repo.get_clients(db, token_session["adminUserId"])
        filtered = [c for c in admin_clients if c.id in client_ids]
        return to_camel_list(filtered)

    user_id = get_user_id(request)
    membership = await team_repo.get_team_membership_by_user_id(db, user_id)
    if membership:
        assigned = await team_repo.get_team_member_clients(db, membership.id)
        client_ids = {ac.client_id for ac in assigned}
        admin_clients = await repo.get_clients(db, membership.admin_user_id)
        filtered = [c for c in admin_clients if c.id in client_ids]
        return to_camel_list(filtered)

    clients = await repo.get_clients(db, user_id)
    return to_camel_list(clients)


class ClientCreate(BaseModel):
    name: str | None = None
    industry: str | None = None
    logoUrl: str | None = None
    primaryColor: str | None = None
    connectionId: int | None = None


@router.post("/api/clients")
async def create_client(
    body: ClientCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    user_id = get_user_id(request)
    if not await is_admin_user(request, db):
        raise HTTPException(status_code=403, detail="Admin access required")

    if body.name is None:
        # Original TS route spreads req.body directly into the insert with no validation,
        # so a missing required `name` column fails at the DB layer, caught by the generic
        # 500 handler ("Failed to create client"). Fail the same way here.
        raise HTTPException(status_code=500, detail="Failed to create client")

    client = await repo.create_client(
        db,
        user_id=user_id,
        name=body.name,
        industry=body.industry,
        logo_url=body.logoUrl,
        primary_color=body.primaryColor,
        connection_id=body.connectionId,
    )
    return to_camel(client)


class ClientUpdate(BaseModel):
    connectionId: int | None = None
    name: str | None = None
    industry: str | None = None
    primaryColor: str | None = None
    logoUrl: str | None = None


@router.patch("/api/clients/{client_id}")
async def update_client(
    client_id: int,
    body: ClientUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    user_id = get_user_id(request)
    if not await is_admin_user(request, db):
        raise HTTPException(status_code=403, detail="Admin access required")

    existing_client = await repo.get_client(db, client_id)
    if existing_client is None or existing_client.user_id != user_id:
        raise HTTPException(status_code=404, detail="Client not found")

    # Whitelist only allowed fields for update, matching the original route's field list.
    fields_set = body.model_fields_set
    allowed_fields: dict = {}
    if "connectionId" in fields_set:
        allowed_fields["connection_id"] = body.connectionId
    if "name" in fields_set:
        allowed_fields["name"] = body.name
    if "industry" in fields_set:
        allowed_fields["industry"] = body.industry
    if "primaryColor" in fields_set:
        allowed_fields["primary_color"] = body.primaryColor
    if "logoUrl" in fields_set:
        allowed_fields["logo_url"] = body.logoUrl

    updated = await repo.update_client(db, client_id, allowed_fields)
    return to_camel(updated)


# ============================================================
# Business Profiles & Product Catalog
# ============================================================


@router.get("/api/business-profile/{client_id}")
async def get_business_profile(
    client_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    get_user_id(request)
    if not await can_access_client(request, db, client_id):
        raise HTTPException(status_code=403, detail="Access denied")
    profile = await repo.get_business_profile(db, client_id)
    return to_camel(profile) if profile is not None else None


class BusinessProfileUpdate(BaseModel):
    description: str | None = None
    targetAudience: str | None = None
    additionalInfo: str | None = None


@router.put("/api/business-profile/{client_id}")
async def upsert_business_profile(
    client_id: int,
    body: BusinessProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    get_user_id(request)
    if not await is_admin_user(request, db):
        raise HTTPException(status_code=403, detail="Admin access required")
    if not await can_access_client(request, db, client_id):
        raise HTTPException(status_code=403, detail="Access denied")

    profile = await repo.upsert_business_profile(
        db,
        client_id=client_id,
        description=body.description,
        target_audience=body.targetAudience,
        additional_info=body.additionalInfo,
    )
    return to_camel(profile)


@router.get("/api/product-catalog/{client_id}")
async def get_product_catalog(
    client_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    get_user_id(request)
    if not await can_access_client(request, db, client_id):
        raise HTTPException(status_code=403, detail="Access denied")
    items = await repo.get_product_catalog(db, client_id)
    return to_camel_list(items)


class ProductCatalogCreate(BaseModel):
    name: str
    description: str | None = None
    benefits: str | None = None
    cost: str | None = None
    price: str | None = None
    category: str | None = None


@router.post("/api/product-catalog/{client_id}")
async def create_product_catalog_item(
    client_id: int,
    body: ProductCatalogCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    get_user_id(request)
    if not await is_admin_user(request, db):
        raise HTTPException(status_code=403, detail="Admin access required")
    if not await can_access_client(request, db, client_id):
        raise HTTPException(status_code=403, detail="Access denied")

    if not body.name or len(body.name) < 1:
        raise HTTPException(status_code=400, detail="Invalid data")

    item = await repo.create_product_catalog_item(
        db,
        client_id=client_id,
        name=body.name,
        description=body.description,
        benefits=body.benefits,
        cost=body.cost,
        price=body.price,
        category=body.category,
    )
    return to_camel(item)


class ProductCatalogUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    benefits: str | None = None
    cost: str | None = None
    price: str | None = None
    category: str | None = None


@router.patch("/api/product-catalog/{client_id}/{item_id}")
async def update_product_catalog_item(
    client_id: int,
    item_id: int,
    body: ProductCatalogUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    get_user_id(request)
    if not await is_admin_user(request, db):
        raise HTTPException(status_code=403, detail="Admin access required")
    if not await can_access_client(request, db, client_id):
        raise HTTPException(status_code=403, detail="Access denied")

    existing_items = await repo.get_product_catalog(db, client_id)
    if not any(item.id == item_id for item in existing_items):
        raise HTTPException(status_code=404, detail="Product not found")

    if body.name is not None and len(body.name) < 1:
        raise HTTPException(status_code=400, detail="Invalid data")

    fields_set = body.model_fields_set
    data = {}
    for camel, snake in (
        ("name", "name"),
        ("description", "description"),
        ("benefits", "benefits"),
        ("cost", "cost"),
        ("price", "price"),
        ("category", "category"),
    ):
        if camel in fields_set:
            data[snake] = getattr(body, camel)

    updated = await repo.update_product_catalog_item(db, item_id, data)
    return to_camel(updated)


@router.delete("/api/product-catalog/{client_id}/{item_id}")
async def delete_product_catalog_item(
    client_id: int,
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    get_user_id(request)
    if not await is_admin_user(request, db):
        raise HTTPException(status_code=403, detail="Admin access required")
    if not await can_access_client(request, db, client_id):
        raise HTTPException(status_code=403, detail="Access denied")

    existing_items = await repo.get_product_catalog(db, client_id)
    if not any(item.id == item_id for item in existing_items):
        raise HTTPException(status_code=404, detail="Product not found")

    await repo.delete_product_catalog_item(db, item_id)
    return {"success": True}
