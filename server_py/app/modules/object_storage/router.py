"""Port of:
  - server/replit_integrations/object_storage/routes.ts (presigned upload URL + /objects serve-back)
  - the `POST /api/profile/avatar` route in server/routes.ts (~lines 309-343)
"""

import logging

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_user_id, require_authenticated
from app.modules.object_storage.object_storage import (
    ObjectNotFoundError,
    ObjectStorageService,
)
from app.modules.team import repo as team_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["object-storage"])

_service = ObjectStorageService()

ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


class UploadUrlRequest(BaseModel):
    name: str | None = None
    size: int | None = None
    contentType: str | None = None


@router.post("/api/uploads/request-url")
async def request_upload_url(body: UploadUrlRequest):
    try:
        if not body.name:
            raise HTTPException(status_code=400, detail="Missing required field: name")

        upload_url = await _service.get_object_entity_upload_url()
        object_path = _service.normalize_object_entity_path(upload_url)

        return {
            "uploadURL": upload_url,
            "objectPath": object_path,
            "metadata": {"name": body.name, "size": body.size, "contentType": body.contentType},
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error generating upload URL")
        raise HTTPException(status_code=500, detail="Failed to generate upload URL")


@router.get("/objects/{category}/{object_id}")
async def serve_object(category: str, object_id: str, request: Request):
    try:
        object_file = await _service.get_object_entity_file(request.url.path)
        content, content_type, cache_control = await _service.download_object(object_file)
        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": cache_control},
        )
    except ObjectNotFoundError:
        raise HTTPException(status_code=404, detail="Object not found")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error serving object")
        raise HTTPException(status_code=500, detail="Failed to serve object")


@router.post("/api/profile/avatar")
async def upload_avatar(
    request: Request,
    db: AsyncSession = Depends(get_db),
    avatar: UploadFile | None = File(None),
    _=Depends(require_authenticated),
):
    try:
        user_id = get_user_id(request)

        if avatar is None:
            raise HTTPException(status_code=400, detail="No file uploaded")

        if avatar.content_type not in ALLOWED_AVATAR_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only JPEG, PNG, GIF, and WebP are allowed.",
            )

        file_bytes = await avatar.read()
        if len(file_bytes) > MAX_AVATAR_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 5MB.")

        upload_url = await _service.get_object_entity_upload_url()
        object_path = _service.normalize_object_entity_path(upload_url)

        async with httpx.AsyncClient() as client:
            upload_response = await client.put(
                upload_url,
                content=file_bytes,
                headers={"Content-Type": avatar.content_type},
            )

        if upload_response.status_code >= 400:
            raise RuntimeError(f"Failed to upload to object storage: {upload_response.status_code}")

        await team_repo.update_user(db, user_id, profile_image_url=object_path)
        return {"profileImageUrl": object_path}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error uploading avatar")
        raise HTTPException(status_code=500, detail="Failed to upload avatar")
