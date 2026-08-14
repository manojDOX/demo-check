from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.serialize import to_camel
from app.db import get_db
from app.dependencies import (
    dev_login,
    get_user_id,
    require_authenticated,
    require_authenticated_or_token,
)
from app.modules.auth import oidc
from app.modules.team import repo as team_repo

router = APIRouter(tags=["auth"])


@router.get("/api/login")
async def login(request: Request):
    settings = get_settings()
    redirect_uri = f"https://{request.url.hostname}/api/callback"
    if settings.NODE_ENV != "production":
        redirect_uri = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}/api/callback"

    url, state, code_verifier = await oidc.build_authorize_url(redirect_uri)
    request.state.session["oauth_pending"] = {
        "state": state,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }
    return RedirectResponse(url)


@router.get("/api/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, db: AsyncSession = Depends(get_db)):
    pending = request.state.session.get("oauth_pending")
    if not pending or not code:
        return RedirectResponse("/api/login")

    try:
        token = await oidc.exchange_code(
            pending["redirect_uri"], code, pending["code_verifier"], pending["state"]
        )
    except Exception:
        return RedirectResponse("/api/login")

    claims = oidc.claims_from_id_token(token)
    await team_repo.upsert_user(
        db,
        id=claims["sub"],
        email=claims.get("email"),
        first_name=claims.get("first_name"),
        last_name=claims.get("last_name"),
        profile_image_url=claims.get("profile_image_url"),
    )

    request.state.session.pop("oauth_pending", None)
    request.state.session["user"] = {
        "claims": claims,
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "expires_at": claims.get("exp"),
    }
    return RedirectResponse("/")


@router.get("/api/logout")
async def logout(request: Request):
    request.state.session.pop("user", None)
    settings = get_settings()
    post_logout = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    if not settings.REPL_ID:
        return RedirectResponse(post_logout)
    url = await oidc.build_end_session_url(post_logout)
    return RedirectResponse(url)


if get_settings().DEV_AUTH_BYPASS:

    @router.get("/api/dev-login")
    async def dev_login_route(request: Request, db: AsyncSession = Depends(get_db)):
        await dev_login(request, db)
        return RedirectResponse("/")


@router.get("/api/auth/token-session")
async def token_session_status(request: Request, db: AsyncSession = Depends(get_db)):
    token_session = request.state.session.get("tokenAuth")
    if not token_session:
        return {"authenticated": False}
    member = await team_repo.get_team_member(db, token_session["teamMemberId"])
    if member is None:
        request.state.session.pop("tokenAuth", None)
        return {"authenticated": False}
    assigned = await team_repo.get_team_member_clients(db, member.id)
    return {
        "authenticated": True,
        "email": member.email,
        "role": member.role,
        "teamMemberId": member.id,
        "adminUserId": member.admin_user_id,
        "assignedClientIds": [ac.client_id for ac in assigned],
    }


@router.get("/api/shared/logout")
async def shared_logout(request: Request):
    request.state.session.pop("tokenAuth", None)
    return RedirectResponse("/")


@router.get("/api/shared/{token}")
async def shared_token_login(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    member = await team_repo.get_team_member_by_share_token(db, token)
    if member is None:
        raise HTTPException(status_code=404, detail="Invalid or expired link")

    request.state.session["tokenAuth"] = {
        "adminUserId": member.admin_user_id,
        "teamMemberId": member.id,
        "email": member.email,
        "role": member.role,
    }

    if member.status == "pending":
        await team_repo.update_team_member_status(db, member.id, "active")

    return RedirectResponse("/")


@router.get("/api/auth/role")
async def auth_role(
    request: Request, db: AsyncSession = Depends(get_db), _=Depends(require_authenticated_or_token)
):
    token_session = request.state.session.get("tokenAuth")
    if token_session:
        assigned = await team_repo.get_team_member_clients(db, token_session["teamMemberId"])
        return {
            "role": token_session.get("role", "viewer"),
            "adminUserId": token_session["adminUserId"],
            "teamMemberId": token_session["teamMemberId"],
            "allowedClientIds": [ac.client_id for ac in assigned],
            "isTokenSession": True,
        }

    user_id = get_user_id(request)
    user = await team_repo.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    membership = await team_repo.get_team_membership_by_user_id(db, user_id)
    if membership:
        assigned = await team_repo.get_team_member_clients(db, membership.id)
        return {
            "role": "viewer",
            "adminUserId": membership.admin_user_id,
            "teamMemberId": membership.id,
            "allowedClientIds": [ac.client_id for ac in assigned],
        }

    return {"role": "admin"}


@router.get("/api/auth/user")
async def get_auth_user(
    request: Request, db: AsyncSession = Depends(get_db), _=Depends(require_authenticated)
):
    """Port of server/replit_integrations/auth/routes.ts's registerAuthRoutes — the
    frontend's useAuth() hook polls this to decide authenticated vs. landing-page state.
    OIDC-only (matches the original's isAuthenticated gate, no token-session fallback)."""
    user_id = get_user_id(request)
    user = await team_repo.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return to_camel(user)


@router.get("/api/profile")
async def get_profile(
    request: Request, db: AsyncSession = Depends(get_db), _=Depends(require_authenticated_or_token)
):
    token_session = request.state.session.get("tokenAuth")
    if token_session:
        return {
            "id": f"token-{token_session['teamMemberId']}",
            "email": token_session["email"],
            "firstName": token_session["email"].split("@")[0],
            "lastName": "",
            "company": "",
            "profileImageUrl": None,
        }
    user_id = get_user_id(request)
    user = await team_repo.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "company": user.company,
        "profileImageUrl": user.profile_image_url,
    }


class ProfileUpdate(BaseModel):
    firstName: str | None = None
    lastName: str | None = None
    email: EmailStr | None = None
    company: str | None = None


@router.patch("/api/profile")
async def update_profile(
    body: ProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated),
):
    from datetime import datetime

    user_id = get_user_id(request)
    user = await team_repo.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if body.firstName is not None:
        user.first_name = body.firstName
    if body.lastName is not None:
        user.last_name = body.lastName
    if body.email is not None:
        user.email = body.email
    if body.company is not None:
        user.company = body.company
    # users.updated_at is TIMESTAMP WITHOUT TIME ZONE — must store a naive datetime.
    user.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "company": user.company,
        "profileImageUrl": user.profile_image_url,
    }
