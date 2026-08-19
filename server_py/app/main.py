import asyncio
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.session_store import PostgresSessionMiddleware

settings = get_settings()

# Directory containing alembic.ini — app/main.py -> app/ -> server_py/.
_SERVER_PY_DIR = Path(__file__).resolve().parents[1]


def _run_pending_migrations() -> None:
    """Runs `alembic upgrade head` as a subprocess against the same interpreter/venv this
    server runs under, so a deploy can never again leave the DB schema behind the code that
    expects it (see the ChatSession.history_cleared_at incident: the column was added to
    the model without the migration being applied, and every query touching ChatSession
    500'd until someone ran this by hand). A subprocess — not alembic's Python API called
    in-process — because alembic/env.py's run_migrations_online() unconditionally calls
    asyncio.run(), which raises if invoked from inside the event loop this FastAPI app is
    already running on. Logged, not raised: a migration failure (e.g. a genuine schema
    conflict needing a human) shouldn't take down routes unrelated to the affected tables."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_SERVER_PY_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(
                "[startup] alembic upgrade head FAILED "
                f"(exit {result.returncode}) — DB schema may be behind the code:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        else:
            print("[startup] alembic upgrade head: database schema is up to date")
    except Exception as exc:  # noqa: BLE001 - never block server startup on this
        print(f"[startup] alembic upgrade head errored: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(_run_pending_migrations)
    yield


app = FastAPI(title="XIOMARA API", lifespan=lifespan)

# Server-side session store, backed by the `sessions` table (Replit-Auth-mandatory shape).
app.add_middleware(PostgresSessionMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """The frontend's apiRequest() reads `parsed.error` (falling back to `.message`) from
    error bodies — FastAPI's default {"detail": ...} shape matches neither, so reshape it
    to match the contract every existing route handler (and the frontend) already expects."""
    body = exc.detail if isinstance(exc.detail, dict) else {"error": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.middleware("http")
async def request_timeout_and_logging(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = int((time.time() - start) * 1000)
    if request.url.path.startswith("/api"):
        print(f"{request.method} {request.url.path} {response.status_code} {duration_ms}ms")
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# --- API routers are mounted here as each module is ported (M2/M3/M4) ---
from app.modules.audio.router import router as audio_router
from app.modules.auth.router import router as auth_router
from app.modules.chat_bot.router import router as chat_bot_router
from app.modules.clients.router import router as clients_router
from app.modules.connections.router import router as connections_router
from app.modules.ghl.router import router as ghl_router
from app.modules.kpi.router import router as kpi_router
from app.modules.object_storage.router import router as object_storage_router
from app.modules.page_builder.router import router as page_builder_router
from app.modules.segments.router import router as segments_router
from app.modules.team.router import router as team_router

app.include_router(audio_router)
app.include_router(auth_router)
app.include_router(chat_bot_router)
app.include_router(clients_router)
app.include_router(connections_router)
app.include_router(ghl_router)
app.include_router(kpi_router)
app.include_router(object_storage_router)
app.include_router(page_builder_router)
app.include_router(segments_router)
app.include_router(team_router)


# --- Static frontend (built Vite client) — must be registered LAST so /api/* wins ---
# vite.config.ts's build.outDir is repo-root `dist/public` (not client/dist).
CLIENT_DIST = Path(__file__).resolve().parents[2] / "dist" / "public"

if CLIENT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=CLIENT_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = CLIENT_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(CLIENT_DIST / "index.html")
else:

    @app.get("/")
    async def dev_placeholder():
        return JSONResponse(
            {
                "message": "dist/public not built yet — run `npx vite build` from the repo root, "
                "or use the Vite dev server directly during frontend-only development."
            }
        )
