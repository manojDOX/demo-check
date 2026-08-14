"""Data-access helpers for clients / business-profiles / product-catalog.

Mirrors the relevant bits of server/storage.ts (DatabaseStorage class):
getClients, getClient, createClient, updateClient, getBusinessProfile,
upsertBusinessProfile, getProductCatalog, createProductCatalogItem,
updateProductCatalogItem, deleteProductCatalogItem.
"""

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import BusinessProfile, Client, ProductCatalogItem


async def get_clients(db: AsyncSession, user_id: str) -> list[Client]:
    result = await db.execute(
        select(Client).where(Client.user_id == user_id).order_by(desc(Client.created_at))
    )
    return list(result.scalars().all())


async def get_client(db: AsyncSession, client_id: int) -> Client | None:
    result = await db.execute(select(Client).where(Client.id == client_id))
    return result.scalar_one_or_none()


async def create_client(
    db: AsyncSession,
    *,
    user_id: str,
    name: str,
    industry: str | None = None,
    logo_url: str | None = None,
    primary_color: str | None = None,
    connection_id: int | None = None,
) -> Client:
    kwargs = {"user_id": user_id, "name": name}
    if industry is not None:
        kwargs["industry"] = industry
    if logo_url is not None:
        kwargs["logo_url"] = logo_url
    if primary_color is not None:
        kwargs["primary_color"] = primary_color
    if connection_id is not None:
        kwargs["connection_id"] = connection_id
    client = Client(**kwargs)
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def update_client(db: AsyncSession, client_id: int, data: dict) -> Client | None:
    client = await get_client(db, client_id)
    if client is None:
        return None
    for key, value in data.items():
        setattr(client, key, value)
    await db.commit()
    await db.refresh(client)
    return client


async def get_business_profile(db: AsyncSession, client_id: int) -> BusinessProfile | None:
    result = await db.execute(select(BusinessProfile).where(BusinessProfile.client_id == client_id))
    return result.scalar_one_or_none()


async def upsert_business_profile(
    db: AsyncSession,
    *,
    client_id: int,
    description: str | None,
    target_audience: str | None,
    additional_info: str | None,
) -> BusinessProfile:
    existing = await get_business_profile(db, client_id)
    if existing is not None:
        existing.description = description
        existing.target_audience = target_audience
        existing.additional_info = additional_info
        existing.updated_at = datetime.utcnow()  # TIMESTAMP WITHOUT TIME ZONE column
        await db.commit()
        await db.refresh(existing)
        return existing

    profile = BusinessProfile(
        client_id=client_id,
        description=description,
        target_audience=target_audience,
        additional_info=additional_info,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def get_product_catalog(db: AsyncSession, client_id: int) -> list[ProductCatalogItem]:
    result = await db.execute(
        select(ProductCatalogItem)
        .where(ProductCatalogItem.client_id == client_id)
        .order_by(desc(ProductCatalogItem.created_at))
    )
    return list(result.scalars().all())


async def create_product_catalog_item(
    db: AsyncSession,
    *,
    client_id: int,
    name: str,
    description: str | None,
    benefits: str | None,
    cost: str | None,
    price: str | None,
    category: str | None,
) -> ProductCatalogItem:
    item = ProductCatalogItem(
        client_id=client_id,
        name=name,
        description=description,
        benefits=benefits,
        cost=cost,
        price=price,
        category=category,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_product_catalog_item(db: AsyncSession, item_id: int, data: dict) -> ProductCatalogItem | None:
    result = await db.execute(select(ProductCatalogItem).where(ProductCatalogItem.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        return None
    for key, value in data.items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def delete_product_catalog_item(db: AsyncSession, item_id: int) -> None:
    result = await db.execute(select(ProductCatalogItem).where(ProductCatalogItem.id == item_id))
    item = result.scalar_one_or_none()
    if item is not None:
        await db.delete(item)
        await db.commit()
