"""Page Builder ("Dynamic Persona") API — mechanical port of the Page Builder section of
server/routes.ts (search: "Page Builder API" through the end of the file) plus the
corresponding storage.ts data-access methods (getPages/getPage/createPage/... through
getSectionTemplates/createSectionTemplate/deleteSectionTemplate).

Note: routes.ts has NO backend surface for content-library, personalization-zones,
anonymous-visitors, or navigation-events despite matching SQLAlchemy models existing
(app/models/page_builder.py, app/models/content_library.py) — those are DB tables with
no routes, and the frontend (client/src/pages/page-builder.tsx, dynamic-persona.tsx,
client/src/components/page-builder/*) never calls any such endpoints either. Nothing was
built for them here; see the final report for details.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import to_camel, to_camel_list
from app.db import get_db
from app.dependencies import get_user_id, require_authenticated
from app.models.page_builder import PageDesign, PageSection, PageVersion, SectionTemplate

router = APIRouter(tags=["page-builder"], dependencies=[Depends(require_authenticated)])


# ------------------------------------------------------------------
# Ownership helpers — ports of routes.ts's verifyPageOwnership / verifyVersionOwnership
# ------------------------------------------------------------------


async def _get_page(db: AsyncSession, page_id: int) -> PageDesign | None:
    result = await db.execute(select(PageDesign).where(PageDesign.id == page_id))
    return result.scalar_one_or_none()


async def _get_version(db: AsyncSession, version_id: int) -> PageVersion | None:
    result = await db.execute(select(PageVersion).where(PageVersion.id == version_id))
    return result.scalar_one_or_none()


async def _get_section(db: AsyncSession, section_id: int) -> PageSection | None:
    result = await db.execute(select(PageSection).where(PageSection.id == section_id))
    return result.scalar_one_or_none()


async def _verify_page_ownership(db: AsyncSession, page_id: int, user_id: str) -> bool:
    page = await _get_page(db, page_id)
    return page is not None and page.user_id == user_id


async def _verify_version_ownership(db: AsyncSession, version_id: int, user_id: str) -> bool:
    version = await _get_version(db, version_id)
    if version is None:
        return False
    return await _verify_page_ownership(db, version.page_id, user_id)


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------


class CreatePageBody(BaseModel):
    name: str
    slug: str | None = None
    clientId: int | None = None


class UpdatePageBody(BaseModel):
    name: str | None = None
    slug: str | None = None
    clientId: int | None = None
    isPublished: bool | None = None
    publishedVersionId: int | None = None


@router.get("/api/pages")
async def get_pages(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        result = await db.execute(
            select(PageDesign).where(PageDesign.user_id == user_id).order_by(PageDesign.updated_at.desc())
        )
        pages = result.scalars().all()
        return to_camel_list(pages)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch pages")


@router.get("/api/pages/{id}")
async def get_page(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        page = await _get_page(db, id)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found")
        if page.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        return to_camel(page)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch page")


@router.post("/api/pages")
async def create_page(body: CreatePageBody, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        if body.slug:
            slug = body.slug
        else:
            import re

            # port of node's `slug || name.toLowerCase().replace(/\s+/g, '-')`
            slug = re.sub(r"\s+", "-", body.name.lower())

        page = PageDesign(
            user_id=user_id,
            name=body.name,
            slug=slug,
            client_id=body.clientId,
            is_published=False,
        )
        db.add(page)
        await db.flush()

        version = PageVersion(
            page_id=page.id,
            version_name="Version 1",
            version_number=1,
            is_active=True,
        )
        db.add(version)
        await db.commit()
        await db.refresh(page)
        await db.refresh(version)

        result = to_camel(page)
        result["activeVersionId"] = version.id
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create page")


@router.put("/api/pages/{id}")
async def update_page(id: int, body: UpdatePageBody, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        page = await _get_page(db, id)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found")
        if page.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        data = body.model_dump(exclude_unset=True)
        field_map = {
            "name": "name",
            "slug": "slug",
            "clientId": "client_id",
            "isPublished": "is_published",
            "publishedVersionId": "published_version_id",
        }
        for key, value in data.items():
            attr = field_map.get(key)
            if attr:
                setattr(page, attr, value)

        from datetime import datetime

        page.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(page)
        return to_camel(page)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update page")


@router.delete("/api/pages/{id}")
async def delete_page(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        page = await _get_page(db, id)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found")
        if page.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        await db.delete(page)
        await db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete page")


# ------------------------------------------------------------------
# Page Versions
# ------------------------------------------------------------------


class CreateVersionBody(BaseModel):
    versionName: str | None = None


class UpdateVersionContentBody(BaseModel):
    htmlContent: str | None = None
    cssContent: str | None = None
    gjsComponents: Any | None = None
    gjsStyles: Any | None = None


@router.get("/api/pages/{page_id}/versions")
async def get_versions(page_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        if not await _verify_page_ownership(db, page_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        result = await db.execute(
            select(PageVersion).where(PageVersion.page_id == page_id).order_by(PageVersion.version_number.desc())
        )
        versions = result.scalars().all()
        return to_camel_list(versions)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch versions")


@router.post("/api/pages/{page_id}/versions")
async def create_version(
    page_id: int, body: CreateVersionBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        if not await _verify_page_ownership(db, page_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")

        result = await db.execute(select(PageVersion).where(PageVersion.page_id == page_id))
        existing_versions = result.scalars().all()
        next_number = len(existing_versions) + 1

        version = PageVersion(
            page_id=page_id,
            version_name=body.versionName or f"Version {next_number}",
            version_number=next_number,
            is_active=False,
        )
        db.add(version)
        await db.commit()
        await db.refresh(version)
        return to_camel(version)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create version")


@router.put("/api/versions/{id}/activate")
async def activate_version(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        version = await _get_version(db, id)
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        if not await _verify_page_ownership(db, version.page_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")

        result = await db.execute(select(PageVersion).where(PageVersion.page_id == version.page_id))
        all_versions = result.scalars().all()
        for v in all_versions:
            if v.id != id:
                v.is_active = False

        version.is_active = True
        await db.commit()
        await db.refresh(version)
        return to_camel(version)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to activate version")


@router.put("/api/versions/{id}")
async def update_version(
    id: int, body: UpdateVersionContentBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        version = await _get_version(db, id)
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        if not await _verify_page_ownership(db, version.page_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")

        # z.object({htmlContent: z.string().max(500000), cssContent: z.string().max(100000), ...}).optional()
        if body.htmlContent is not None and len(body.htmlContent) > 500000:
            raise HTTPException(status_code=400, detail="Invalid request data")
        if body.cssContent is not None and len(body.cssContent) > 100000:
            raise HTTPException(status_code=400, detail="Invalid request data")

        data = body.model_dump(exclude_unset=True)
        if "htmlContent" in data:
            version.html_content = data["htmlContent"]
        if "cssContent" in data:
            version.css_content = data["cssContent"]
        if "gjsComponents" in data:
            version.gjs_components = data["gjsComponents"]
        if "gjsStyles" in data:
            version.gjs_styles = data["gjsStyles"]

        await db.commit()
        await db.refresh(version)
        return to_camel(version)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update version")


@router.delete("/api/versions/{id}")
async def delete_version(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        version = await _get_version(db, id)
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        if not await _verify_page_ownership(db, version.page_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        await db.delete(version)
        await db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete version")


# ------------------------------------------------------------------
# Page Sections
# ------------------------------------------------------------------


class CreateSectionBody(BaseModel):
    sectionType: str
    content: dict | None = None
    styles: dict | None = None


class UpdateSectionBody(BaseModel):
    sectionType: str | None = None
    sectionOrder: int | None = None
    content: dict | None = None
    styles: dict | None = None
    isVisible: bool | None = None


class ReorderSectionsBody(BaseModel):
    sectionIds: list[int]


@router.get("/api/versions/{version_id}/sections")
async def get_sections(version_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        if not await _verify_version_ownership(db, version_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        result = await db.execute(
            select(PageSection).where(PageSection.version_id == version_id).order_by(PageSection.section_order)
        )
        sections = result.scalars().all()
        return to_camel_list(sections)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch sections")


@router.post("/api/versions/{version_id}/sections")
async def create_section(
    version_id: int, body: CreateSectionBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        if not await _verify_version_ownership(db, version_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")

        result = await db.execute(select(PageSection).where(PageSection.version_id == version_id))
        existing_sections = result.scalars().all()
        next_order = len(existing_sections)

        section = PageSection(
            version_id=version_id,
            section_type=body.sectionType,
            section_order=next_order,
            content=body.content or {},
            styles=body.styles or {},
            is_visible=True,
        )
        db.add(section)
        await db.commit()
        await db.refresh(section)
        return to_camel(section)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create section")


@router.put("/api/sections/{id}")
async def update_section(
    id: int, body: UpdateSectionBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        section = await _get_section(db, id)
        if section is None:
            raise HTTPException(status_code=404, detail="Section not found")
        if not await _verify_version_ownership(db, section.version_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")

        data = body.model_dump(exclude_unset=True)
        field_map = {
            "sectionType": "section_type",
            "sectionOrder": "section_order",
            "content": "content",
            "styles": "styles",
            "isVisible": "is_visible",
        }
        for key, value in data.items():
            attr = field_map.get(key)
            if attr:
                setattr(section, attr, value)

        from datetime import datetime

        section.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(section)
        return to_camel(section)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update section")


@router.delete("/api/sections/{id}")
async def delete_section(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        section = await _get_section(db, id)
        if section is None:
            raise HTTPException(status_code=404, detail="Section not found")
        if not await _verify_version_ownership(db, section.version_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        await db.delete(section)
        await db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete section")


@router.post("/api/versions/{version_id}/sections/reorder")
async def reorder_sections(
    version_id: int, body: ReorderSectionsBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        if not await _verify_version_ownership(db, version_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")

        result = await db.execute(select(PageSection).where(PageSection.version_id == version_id))
        existing_sections = result.scalars().all()
        valid_ids = {s.id for s in existing_sections}
        invalid_ids = [sid for sid in body.sectionIds if sid not in valid_ids]
        if invalid_ids:
            raise HTTPException(status_code=400, detail="Invalid section IDs")

        sections_by_id = {s.id: s for s in existing_sections}
        for order, section_id in enumerate(body.sectionIds):
            sections_by_id[section_id].section_order = order

        await db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to reorder sections")


# ------------------------------------------------------------------
# Section Templates
# ------------------------------------------------------------------


class CreateTemplateBody(BaseModel):
    name: str
    sectionType: str
    content: dict | None = None
    styles: dict | None = None
    thumbnailUrl: str | None = None


@router.get("/api/section-templates")
async def get_section_templates(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        result = await db.execute(
            select(SectionTemplate)
            .where((SectionTemplate.is_system.is_(True)) | (SectionTemplate.user_id == user_id))
            .order_by(SectionTemplate.section_type)
        )
        templates = result.scalars().all()
        return to_camel_list(templates)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch templates")


@router.post("/api/section-templates")
async def create_section_template(
    body: CreateTemplateBody, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        user_id = get_user_id(request)
        template = SectionTemplate(
            user_id=user_id,
            name=body.name,
            section_type=body.sectionType,
            content=body.content or {},
            styles=body.styles or {},
            thumbnail_url=body.thumbnailUrl,
            is_system=False,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return to_camel(template)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create template")


@router.delete("/api/section-templates/{id}")
async def delete_section_template(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user_id = get_user_id(request)
        result = await db.execute(select(SectionTemplate).where(SectionTemplate.id == id))
        template = result.scalar_one_or_none()
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        if template.is_system:
            raise HTTPException(status_code=403, detail="Cannot delete system templates")
        if template.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        await db.delete(template)
        await db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete template")
