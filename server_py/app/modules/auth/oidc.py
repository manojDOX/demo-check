"""Replit OIDC (Authlib), a functional port of server/replit_integrations/auth/replitAuth.ts.

Port notes vs. the Node version:
- openid-client's `client.discovery(ISSUER_URL, REPL_ID)` + passport Strategy is replaced by
  Authlib's AsyncOAuth2Client against the discovered .well-known/openid-configuration document.
- No client_secret is used (public client + PKCE), matching the original.
- Session storage of claims/access_token/refresh_token/expires_at is handled by the caller
  (router.py) via request.state.session — this module only talks to the OIDC provider.
"""

import time
from functools import lru_cache

import httpx
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import AsyncOAuth2Client

from app.config import get_settings

SCOPE = "openid email profile offline_access"


@lru_cache
def _settings():
    return get_settings()


async def get_oidc_metadata() -> dict:
    settings = _settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.ISSUER_URL.rstrip('/')}/.well-known/openid-configuration")
        resp.raise_for_status()
        return resp.json()


def build_oauth_client(redirect_uri: str) -> AsyncOAuth2Client:
    settings = _settings()
    return AsyncOAuth2Client(
        client_id=settings.REPL_ID,
        scope=SCOPE,
        redirect_uri=redirect_uri,
        code_challenge_method="S256",
    )


async def build_authorize_url(redirect_uri: str) -> tuple[str, str, str]:
    """Returns (authorize_url, state, code_verifier).

    Authlib's AsyncOAuth2Client does not generate/store a PKCE code_verifier on its own —
    the caller must generate one and pass it explicitly to both create_authorization_url
    (so it can derive+send the code_challenge) and later to fetch_token (to prove
    possession). We generate it here and hand it back to the caller (router.py) to persist
    in the session between the /api/login redirect and the /api/callback round-trip.
    """
    metadata = await get_oidc_metadata()
    client = build_oauth_client(redirect_uri)
    code_verifier = generate_token(48)
    url, state = client.create_authorization_url(
        metadata["authorization_endpoint"],
        code_verifier=code_verifier,
        prompt="login",
        screen_hint="login",
    )
    return url, state, code_verifier


async def exchange_code(
    redirect_uri: str, code: str, code_verifier: str, state: str
) -> dict:
    metadata = await get_oidc_metadata()
    client = build_oauth_client(redirect_uri)
    token = await client.fetch_token(
        metadata["token_endpoint"],
        code=code,
        code_verifier=code_verifier,
        grant_type="authorization_code",
    )
    return token


async def refresh_token_grant(refresh_token: str) -> dict:
    settings = _settings()
    metadata = await get_oidc_metadata()
    client = AsyncOAuth2Client(client_id=settings.REPL_ID)
    token = await client.refresh_token(metadata["token_endpoint"], refresh_token=refresh_token)
    return token


async def build_end_session_url(post_logout_redirect_uri: str) -> str:
    settings = _settings()
    metadata = await get_oidc_metadata()
    end_session_endpoint = metadata.get("end_session_endpoint")
    if not end_session_endpoint:
        return post_logout_redirect_uri
    return (
        f"{end_session_endpoint}?client_id={settings.REPL_ID}"
        f"&post_logout_redirect_uri={post_logout_redirect_uri}"
    )


def claims_from_id_token(token: dict) -> dict:
    """Authlib's fetch_token already validates + decodes the id_token into userinfo
    when using AsyncOAuth2Client without OpenID extension helpers, so we parse it manually
    via the `userinfo` claims embedded by Authlib's OpenIDMixin if present, else fall back
    to a raw JWT decode of id_token (Replit's issuer is trusted/discovered above)."""
    if "userinfo" in token:
        return dict(token["userinfo"])
    # Fallback: decode without re-verifying signature (already over TLS to a discovered,
    # trusted issuer) — payload only, matching what claims() gives the Node client.
    import base64
    import json

    id_token = token.get("id_token")
    if not id_token:
        return {}
    payload_b64 = id_token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def is_expired(expires_at: int | None) -> bool:
    if expires_at is None:
        return True
    return time.time() > expires_at
