"""Port of server/replit_integrations/object_storage/objectStorage.ts.

Replit's object storage sidecar issues short-lived GCS access tokens over a local
HTTP endpoint. The Node client authenticates the `@google-cloud/storage` SDK against
that sidecar using an `external_account` credential (Workload Identity Federation
shape) whose `credential_source.url` points at the sidecar's `/credential` endpoint.

We replicate that exact credential shape here with `google.auth.identity_pool.Credentials`
so `google-cloud-storage`'s Python client authenticates the same way the TS client does:
  - audience: "replit"
  - subject_token_type: "access_token"
  - token_url: http://127.0.0.1:1106/token
  - credential_source.url: http://127.0.0.1:1106/credential
  - credential_source.format: {"type": "json", "subject_token_field_name": "access_token"}

Signing upload/download URLs, however, is NOT done via the GCS client's own signing
(which would need a private key we don't have) — like the TS code, it's a raw POST to
the sidecar's `/object-storage/signed-object-url` endpoint.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.concurrency import run_in_threadpool
from google.auth import identity_pool
from google.cloud.storage import Blob, Client as StorageClient

from app.config import get_settings
from app.modules.object_storage.object_acl import (
    ObjectAclPolicy,
    ObjectPermission,
    can_access_object,
    get_object_acl_policy,
    set_object_acl_policy,
)

REPLIT_SIDECAR_ENDPOINT = "http://127.0.0.1:1106"


class ObjectNotFoundError(Exception):
    pass


def _build_credentials() -> identity_pool.Credentials:
    return identity_pool.Credentials(
        audience="replit",
        subject_token_type="access_token",
        token_url=f"{REPLIT_SIDECAR_ENDPOINT}/token",
        credential_source={
            "url": f"{REPLIT_SIDECAR_ENDPOINT}/credential",
            "format": {
                "type": "json",
                "subject_token_field_name": "access_token",
            },
        },
    )


# Lazily built so importing this module doesn't require the sidecar to be reachable.
_storage_client: StorageClient | None = None


def get_object_storage_client() -> StorageClient:
    global _storage_client
    if _storage_client is None:
        _storage_client = StorageClient(credentials=_build_credentials(), project="")
    return _storage_client


def _parse_object_path(path: str) -> tuple[str, str]:
    if not path.startswith("/"):
        path = f"/{path}"
    parts = path.split("/")
    if len(parts) < 3:
        raise ValueError("Invalid path: must contain at least a bucket name")
    bucket_name = parts[1]
    object_name = "/".join(parts[2:])
    return bucket_name, object_name


async def _sign_object_url(
    *, bucket_name: str, object_name: str, method: str, ttl_sec: int
) -> str:
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_sec)).isoformat()
    payload = {
        "bucket_name": bucket_name,
        "object_name": object_name,
        "method": method,
        "expires_at": expires_at,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{REPLIT_SIDECAR_ENDPOINT}/object-storage/signed-object-url",
            json=payload,
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to sign object URL, errorcode: {response.status_code}, "
            "make sure you're running on Replit"
        )
    return response.json()["signed_url"]


class ObjectStorageService:
    def get_public_object_search_paths(self) -> list[str]:
        settings = get_settings()
        paths_str = settings.PUBLIC_OBJECT_SEARCH_PATHS or ""
        paths = list(
            dict.fromkeys(p.strip() for p in paths_str.split(",") if p.strip())
        )
        if not paths:
            raise RuntimeError(
                "PUBLIC_OBJECT_SEARCH_PATHS not set. Create a bucket in 'Object Storage' "
                "tool and set PUBLIC_OBJECT_SEARCH_PATHS env var (comma-separated paths)."
            )
        return paths

    def get_private_object_dir(self) -> str:
        settings = get_settings()
        directory = settings.PRIVATE_OBJECT_DIR or ""
        if not directory:
            raise RuntimeError(
                "PRIVATE_OBJECT_DIR not set. Create a bucket in 'Object Storage' "
                "tool and set PRIVATE_OBJECT_DIR env var."
            )
        return directory

    async def search_public_object(self, file_path: str) -> Blob | None:
        client = get_object_storage_client()
        for search_path in self.get_public_object_search_paths():
            full_path = f"{search_path}/{file_path}"
            bucket_name, object_name = _parse_object_path(full_path)

            def _lookup(bucket_name=bucket_name, object_name=object_name):
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(object_name)
                return blob if blob.exists() else None

            blob = await run_in_threadpool(_lookup)
            if blob is not None:
                return blob
        return None

    async def download_object(self, blob: Blob, cache_ttl_sec: int = 3600):
        """Returns (content_bytes, content_type, cache_control) for the caller to build
        a Response with — the async equivalent of the TS version's res.set()+stream.pipe()."""

        def _fetch():
            blob.reload()
            acl_policy = get_object_acl_policy(blob)
            is_public = bool(acl_policy and acl_policy.visibility == "public")
            content = blob.download_as_bytes()
            return content, blob.content_type or "application/octet-stream", is_public

        content, content_type, is_public = await run_in_threadpool(_fetch)
        cache_control = f"{'public' if is_public else 'private'}, max-age={cache_ttl_sec}"
        return content, content_type, cache_control

    async def get_object_entity_upload_url(self) -> str:
        private_object_dir = self.get_private_object_dir()
        object_id = str(uuid.uuid4())
        full_path = f"{private_object_dir}/uploads/{object_id}"
        bucket_name, object_name = _parse_object_path(full_path)
        return await _sign_object_url(
            bucket_name=bucket_name, object_name=object_name, method="PUT", ttl_sec=900
        )

    async def get_object_entity_file(self, object_path: str) -> Blob:
        if not object_path.startswith("/objects/"):
            raise ObjectNotFoundError()

        parts = object_path[1:].split("/")
        if len(parts) < 2:
            raise ObjectNotFoundError()

        entity_id = "/".join(parts[1:])
        entity_dir = self.get_private_object_dir()
        if not entity_dir.endswith("/"):
            entity_dir = f"{entity_dir}/"
        object_entity_path = f"{entity_dir}{entity_id}"
        bucket_name, object_name = _parse_object_path(object_entity_path)

        client = get_object_storage_client()

        def _lookup():
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(object_name)
            if not blob.exists():
                raise ObjectNotFoundError()
            return blob

        return await run_in_threadpool(_lookup)

    def normalize_object_entity_path(self, raw_path: str) -> str:
        if not raw_path.startswith("https://storage.googleapis.com/"):
            return raw_path

        from urllib.parse import urlparse

        raw_object_path = urlparse(raw_path).path

        object_entity_dir = self.get_private_object_dir()
        if not object_entity_dir.endswith("/"):
            object_entity_dir = f"{object_entity_dir}/"

        if not raw_object_path.startswith(object_entity_dir):
            return raw_object_path

        entity_id = raw_object_path[len(object_entity_dir):]
        return f"/objects/{entity_id}"

    async def try_set_object_entity_acl_policy(
        self, raw_path: str, acl_policy: ObjectAclPolicy
    ) -> str:
        normalized_path = self.normalize_object_entity_path(raw_path)
        if not normalized_path.startswith("/"):
            return normalized_path

        blob = await self.get_object_entity_file(normalized_path)
        await run_in_threadpool(set_object_acl_policy, blob, acl_policy)
        return normalized_path

    async def can_access_object_entity(
        self,
        *,
        user_id: str | None,
        blob: Blob,
        requested_permission: ObjectPermission = ObjectPermission.READ,
    ) -> bool:
        return await run_in_threadpool(
            can_access_object,
            user_id=user_id,
            blob=blob,
            requested_permission=requested_permission,
        )
