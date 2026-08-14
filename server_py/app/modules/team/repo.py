"""Shared data-access helpers used by auth + team modules.

Mirrors the relevant bits of server/storage.ts. Full team CRUD (invite/list/patch/delete)
lands in the M3 mechanical-CRUD-port pass; this module only carries what auth needs.
"""

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.clients import Client
from app.models.team import TeamMember, TeamMemberClient


async def get_user(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def upsert_user(
    db: AsyncSession,
    *,
    id: str,
    email: str | None,
    first_name: str | None,
    last_name: str | None,
    profile_image_url: str | None,
) -> User:
    user = await get_user(db, id)
    if user is None:
        user = User(
            id=id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            profile_image_url=profile_image_url,
        )
        db.add(user)
    else:
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.profile_image_url = profile_image_url
    await db.commit()
    await db.refresh(user)
    return user


async def get_team_membership_by_user_id(db: AsyncSession, user_id: str) -> TeamMember | None:
    """The team-member row where THIS user is the invited collaborator (not the admin)."""
    result = await db.execute(
        select(TeamMember).where(TeamMember.user_id == user_id, TeamMember.status == "active")
    )
    return result.scalars().first()


async def get_team_member(db: AsyncSession, team_member_id: int) -> TeamMember | None:
    result = await db.execute(select(TeamMember).where(TeamMember.id == team_member_id))
    return result.scalar_one_or_none()


async def get_team_member_by_share_token(db: AsyncSession, token: str) -> TeamMember | None:
    result = await db.execute(select(TeamMember).where(TeamMember.share_token == token))
    return result.scalar_one_or_none()


async def update_team_member_status(db: AsyncSession, team_member_id: int, status: str) -> None:
    member = await get_team_member(db, team_member_id)
    if member is not None:
        member.status = status
        await db.commit()


async def get_team_member_clients(db: AsyncSession, team_member_id: int) -> list[TeamMemberClient]:
    result = await db.execute(
        select(TeamMemberClient).where(TeamMemberClient.team_member_id == team_member_id)
    )
    return list(result.scalars().all())


async def get_client(db: AsyncSession, client_id: int) -> Client | None:
    result = await db.execute(select(Client).where(Client.id == client_id))
    return result.scalar_one_or_none()


async def user_can_access_client(db: AsyncSession, user_id: str, client_id: int) -> bool:
    client = await get_client(db, client_id)
    if client is None:
        return False
    if client.user_id == user_id:
        return True
    membership = await get_team_membership_by_user_id(db, user_id)
    if membership is None:
        return False
    if client.user_id != membership.admin_user_id:
        return False
    assigned = await get_team_member_clients(db, membership.id)
    return any(ac.client_id == client_id for ac in assigned)


async def token_user_can_access_client(db: AsyncSession, team_member_id: int, client_id: int) -> bool:
    assigned = await get_team_member_clients(db, team_member_id)
    return any(ac.client_id == client_id for ac in assigned)


# ---------------------------------------------------------------------------
# Team CRUD (port of storage.ts's team-member functions used by the /api/team
# routes) and the small extras those routes need (get_clients, update_user).
# ---------------------------------------------------------------------------


async def update_user(db: AsyncSession, user_id: str, **fields) -> User | None:
    user = await get_user(db, user_id)
    if user is None:
        return None
    for key, value in fields.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


async def get_clients(db: AsyncSession, user_id: str) -> list[Client]:
    result = await db.execute(select(Client).where(Client.user_id == user_id))
    return list(result.scalars().all())


async def get_team_members(db: AsyncSession, admin_user_id: str) -> list[TeamMember]:
    result = await db.execute(
        select(TeamMember)
        .where(TeamMember.admin_user_id == admin_user_id)
        .order_by(desc(TeamMember.created_at))
    )
    return list(result.scalars().all())


async def get_team_member_by_email(db: AsyncSession, admin_user_id: str, email: str) -> TeamMember | None:
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.admin_user_id == admin_user_id, TeamMember.email == email.lower()
        )
    )
    return result.scalar_one_or_none()


async def create_team_member(
    db: AsyncSession,
    *,
    admin_user_id: str,
    email: str,
    role: str = "viewer",
    status: str = "pending",
    user_id: str | None = None,
    share_token: str,
) -> TeamMember:
    member = TeamMember(
        admin_user_id=admin_user_id,
        email=email.lower(),
        role=role,
        status=status,
        user_id=user_id,
        share_token=share_token,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def update_team_member(db: AsyncSession, team_member_id: int, **fields) -> TeamMember | None:
    """Generic field update (not just status) — used by PATCH /api/team/:id and the
    lazy shareToken backfill in GET /api/team."""
    member = await get_team_member(db, team_member_id)
    if member is None:
        return None
    for key, value in fields.items():
        setattr(member, key, value)
    await db.commit()
    await db.refresh(member)
    return member


async def delete_team_member(db: AsyncSession, team_member_id: int) -> None:
    await db.execute(delete(TeamMember).where(TeamMember.id == team_member_id))
    await db.commit()


async def set_team_member_clients(db: AsyncSession, team_member_id: int, client_ids: list[int]) -> None:
    await db.execute(delete(TeamMemberClient).where(TeamMemberClient.team_member_id == team_member_id))
    for client_id in client_ids:
        db.add(TeamMemberClient(team_member_id=team_member_id, client_id=client_id))
    await db.commit()
