"""Auth dependencies — port of the helper functions at the top of server/routes.ts
(getUserId, isAuthenticatedOrToken, isAdminUser, canAccessClient) plus replitAuth.ts's
isAuthenticated (expiry + refresh-token logic).
"""

import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.modules.auth import oidc
from app.modules.team import repo as team_repo


def _token_auth(request: Request) -> dict | None:
    session = getattr(request.state, "session", {}) or {}
    return session.get("tokenAuth")


def _oidc_user(request: Request) -> dict | None:
    session = getattr(request.state, "session", {}) or {}
    return session.get("user")


async def require_authenticated(request: Request) -> None:
    """Port of replitAuth.ts's `isAuthenticated`: OIDC-only (no token-session fallback)."""
    user = _oidc_user(request)
    if not user or not user.get("expires_at"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if time.time() <= user["expires_at"]:
        return

    refresh_token = user.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        token = await oidc.refresh_token_grant(refresh_token)
        claims = oidc.claims_from_id_token(token)
        user["claims"] = claims
        user["access_token"] = token.get("access_token")
        user["refresh_token"] = token.get("refresh_token", refresh_token)
        user["expires_at"] = claims.get("exp")
        request.state.session["user"] = user
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def require_authenticated_or_token(request: Request) -> None:
    """Port of `isAuthenticatedOrToken` — accepts either a valid token-session or OIDC auth."""
    token_session = _token_auth(request)
    if token_session and token_session.get("adminUserId") and token_session.get("teamMemberId"):
        return
    await require_authenticated(request)


def get_user_id(request: Request) -> str:
    """Port of `getUserId` — supports both OIDC and token sessions."""
    token_session = _token_auth(request)
    if token_session:
        return token_session["adminUserId"]
    user = _oidc_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user["claims"]["sub"]


def get_token_team_member_id(request: Request) -> int | None:
    token_session = _token_auth(request)
    return token_session.get("teamMemberId") if token_session else None


async def is_admin_user(request: Request, db: AsyncSession) -> bool:
    """Port of `isAdminUser` — token sessions are always non-admin; admin is implicit
    (no team-membership row for this user)."""
    if _token_auth(request):
        return False
    user_id = get_user_id(request)
    membership = await team_repo.get_team_membership_by_user_id(db, user_id)
    return membership is None


async def can_access_client(request: Request, db: AsyncSession, client_id: int) -> bool:
    """Port of `canAccessClient` — combined access check for OIDC and token sessions."""
    token_session = _token_auth(request)
    if token_session:
        return await team_repo.token_user_can_access_client(db, token_session["teamMemberId"], client_id)
    return await team_repo.user_can_access_client(db, get_user_id(request), client_id)


async def dev_login(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    """Local-only convenience: logs in as a fixed dev user without a real OIDC round-trip.
    Gated behind DEV_AUTH_BYPASS — never true in the Replit deployment build. Mounted as a
    route in auth/router.py, not used as a request dependency."""
    settings = get_settings()
    if not settings.DEV_AUTH_BYPASS:
        raise HTTPException(status_code=404)
    user = await team_repo.get_user_by_email(db, settings.DEV_AUTH_USER_EMAIL)
    if user is None:
        user = await team_repo.upsert_user(
            db,
            id="dev-user-0000-0000-0000-000000000000",
            email=settings.DEV_AUTH_USER_EMAIL,
            first_name="Dev",
            last_name="User",
            profile_image_url=None,
        )
    now = int(time.time())
    request.state.session["user"] = {
        "claims": {
            "sub": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        },
        "access_token": "dev-bypass",
        "refresh_token": None,
        "expires_at": now + 7 * 24 * 3600,
    }
