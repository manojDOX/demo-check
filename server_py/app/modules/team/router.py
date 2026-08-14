"""Team / Collaborators CRUD — port of the `/api/team*` routes in server/routes.ts
(lines ~385-498), backed by app/modules/team/repo.py.
"""

import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import to_camel
from app.db import get_db
from app.dependencies import get_user_id, is_admin_user, require_authenticated_or_token
from app.modules.team import repo as team_repo
from app.modules.team.email import send_team_invite_email

logger = logging.getLogger(__name__)

router = APIRouter(tags=["team"])


def _member_with_clients(member, assigned_clients) -> dict:
    data = to_camel(member)
    data["assignedClientIds"] = [ac.client_id for ac in assigned_clients]
    return data


@router.get("/api/team")
async def list_team_members(
    request: Request, db: AsyncSession = Depends(get_db), _=Depends(require_authenticated_or_token)
):
    try:
        user_id = get_user_id(request)
        members = await team_repo.get_team_members(db, user_id)
        result = []
        for m in members:
            if not m.share_token:
                token = secrets.token_hex(32)
                m = await team_repo.update_team_member(db, m.id, share_token=token)
            assigned_clients = await team_repo.get_team_member_clients(db, m.id)
            result.append(_member_with_clients(m, assigned_clients))
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching team")
        raise HTTPException(status_code=500, detail="Failed to fetch team members")


class InviteTeamMemberBody(BaseModel):
    email: EmailStr
    clientIds: list[int] = Field(min_length=1)


@router.post("/api/team")
async def invite_team_member(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    try:
        user_id = get_user_id(request)
        if not await is_admin_user(request, db):
            raise HTTPException(status_code=403, detail="Admin access required")

        raw_body = await request.json()
        try:
            parsed = InviteTeamMemberBody.model_validate(raw_body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=400, detail={"error": "Invalid data", "details": exc.errors()}
            )

        email = parsed.email
        client_ids = parsed.clientIds

        existing = await team_repo.get_team_member_by_email(db, user_id, email)
        if existing:
            raise HTTPException(status_code=409, detail="This email is already on your team")

        invited_user = await team_repo.get_user_by_email(db, email.lower())

        share_token = secrets.token_hex(32)

        member = await team_repo.create_team_member(
            db,
            admin_user_id=user_id,
            email=email.lower(),
            role="viewer",
            status="active" if invited_user else "pending",
            user_id=invited_user.id if invited_user else None,
            share_token=share_token,
        )

        await team_repo.set_team_member_clients(db, member.id, client_ids)
        assigned_clients = await team_repo.get_team_member_clients(db, member.id)

        admin_user = await team_repo.get_user(db, user_id)
        all_clients = await team_repo.get_clients(db, user_id)
        client_names = [c.name for c in all_clients if c.id in client_ids]

        inviter_name = (
            f"{admin_user.first_name} {admin_user.last_name or ''}".strip()
            if admin_user and admin_user.first_name
            else "Tu administrador"
        )

        background_tasks.add_task(
            send_team_invite_email,
            to_email=email,
            inviter_name=inviter_name,
            client_names=client_names,
            share_token=share_token,
        )

        return _member_with_clients(member, assigned_clients)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error inviting team member")
        raise HTTPException(status_code=500, detail="Failed to invite team member")


class UpdateTeamMemberBody(BaseModel):
    clientIds: list[int] | None = Field(default=None, min_length=1)


@router.patch("/api/team/{member_id}")
async def update_team_member(
    member_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    try:
        user_id = get_user_id(request)
        member = await team_repo.get_team_member(db, member_id)
        if not member or member.admin_user_id != user_id:
            raise HTTPException(status_code=404, detail="Team member not found")

        raw_body = await request.json()
        try:
            parsed = UpdateTeamMemberBody.model_validate(raw_body)
        except ValidationError:
            raise HTTPException(status_code=400, detail="Invalid data")

        if parsed.clientIds is not None:
            await team_repo.set_team_member_clients(db, member_id, parsed.clientIds)

        assigned_clients = await team_repo.get_team_member_clients(db, member_id)
        return _member_with_clients(member, assigned_clients)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error updating team member")
        raise HTTPException(status_code=500, detail="Failed to update team member")


@router.delete("/api/team/{member_id}")
async def delete_team_member(
    member_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_authenticated_or_token),
):
    try:
        user_id = get_user_id(request)
        member = await team_repo.get_team_member(db, member_id)
        if not member or member.admin_user_id != user_id:
            raise HTTPException(status_code=404, detail="Team member not found")
        await team_repo.delete_team_member(db, member_id)
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error removing team member")
        raise HTTPException(status_code=500, detail="Failed to remove team member")
