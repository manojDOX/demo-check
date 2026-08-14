import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.session_store import PostgresSessionMiddleware

settings = get_settings()

app = FastAPI(title="XIOMARA API")

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
