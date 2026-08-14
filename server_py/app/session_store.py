import json
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, Signer
from sqlalchemy import delete, select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.db import SessionLocal
from app.models.auth import Session as SessionRow

SESSION_COOKIE_NAME = "xiomara.sid"
SESSION_TTL = timedelta(days=7)


class PostgresSessionMiddleware(BaseHTTPMiddleware):
    """Server-side session store backed by the exact same `sessions` table
    (sid/sess/expire) that Replit Auth's connect-pg-simple store used.
    Starlette's built-in SessionMiddleware is cookie-only and NOT sufficient here.

    resave:false / saveUninitialized:false semantics: only write a row when the
    session dict actually changed during this request.
    """

    def __init__(self, app):
        super().__init__(app)
        self._signer = Signer(get_settings().SESSION_SECRET)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        raw_sid = request.cookies.get(SESSION_COOKIE_NAME)
        sid: str | None = None
        session_data: dict = {}

        if raw_sid:
            try:
                sid = self._signer.unsign(raw_sid).decode()
            except BadSignature:
                sid = None

        async with SessionLocal() as db:
            if sid:
                result = await db.execute(select(SessionRow).where(SessionRow.sid == sid))
                row = result.scalar_one_or_none()
                now = datetime.now(timezone.utc)
                if row is not None and row.expire.replace(tzinfo=timezone.utc) > now:
                    session_data = dict(row.sess)
                else:
                    sid = None

        request.state.session = session_data
        original = json.dumps(session_data, sort_keys=True, default=str)

        response = await call_next(request)

        new_session = getattr(request.state, "session", {})
        changed = json.dumps(new_session, sort_keys=True, default=str) != original

        if not new_session:
            if sid:
                async with SessionLocal() as db:
                    await db.execute(delete(SessionRow).where(SessionRow.sid == sid))
                    await db.commit()
            response.delete_cookie(SESSION_COOKIE_NAME)
            return response

        if changed or sid is None:
            if sid is None:
                sid = secrets.token_urlsafe(32)
            # `expire` is TIMESTAMP WITHOUT TIME ZONE — store naive UTC to match.
            expire_at = (datetime.now(timezone.utc) + SESSION_TTL).replace(tzinfo=None)
            async with SessionLocal() as db:
                existing = await db.execute(select(SessionRow).where(SessionRow.sid == sid))
                row = existing.scalar_one_or_none()
                if row is None:
                    db.add(SessionRow(sid=sid, sess=new_session, expire=expire_at))
                else:
                    row.sess = new_session
                    row.expire = expire_at
                await db.commit()

            signed = self._signer.sign(sid.encode()).decode()
            response.set_cookie(
                SESSION_COOKIE_NAME,
                signed,
                httponly=True,
                secure=get_settings().NODE_ENV == "production",
                max_age=int(SESSION_TTL.total_seconds()),
                samesite="lax",
            )

        return response
