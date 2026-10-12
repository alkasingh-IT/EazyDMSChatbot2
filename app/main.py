"""
DMS Analytics — Main FastAPI Application
"""
import os
import time
import logging
import multiprocessing
import uvicorn
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config.settings import settings
from .routes import main_router, analytics_router, chat_router, staff_router, export_router, database_router, speech_router, prefs_router
from .db import current_user_id
from .auth import is_public_path, require_request_identity
from fastapi.responses import JSONResponse

# ── Logging configuration ────────────────────────────────────────────────────────
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
_log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format=_log_fmt, datefmt="%Y-%m-%d %H:%M:%S", force=True)
logging.getLogger("dms.db").setLevel(_log_level)
logging.getLogger("sqlalchemy.engine").setLevel(os.environ.get("SQL_LOG_LEVEL", "WARNING").upper())
logging.getLogger("sqlalchemy.pool").setLevel(os.environ.get("SQL_POOL_LOG_LEVEL", "INFO").upper())
for l in ("dms", "dms.db", "dms.chat", "dms.speech", "dms.database"):
    logging.getLogger(l).handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter(_log_fmt, "%Y-%m-%d %H:%M:%S"))
    logging.getLogger(l).addHandler(h)
    logging.getLogger(l).propagate = False

logger = logging.getLogger("dms")
logger.info("Terminal Logging System Configured (level=%s)", _log_level)

# ── Concurrency config ───────────────────────────────────────────────────────────
_CPU_COUNT    = multiprocessing.cpu_count() or 1
# Thread pool: handles sync analytics function calls from FastAPI route handlers.
# Each thread blocks waiting for an asyncpg result, so threads are I/O-idle —
# a large pool (cpu * 50, max 500) allows many concurrent requests without CPU cost.
_THREAD_POOL_SIZE = int(os.environ.get("THREAD_POOL_SIZE", str(min(500, _CPU_COUNT * 50))))
# Worker processes: each is an independent uvicorn event loop + thread pool.
# I/O-bound DB workload → cpu * 2 workers. Cap at 8 to avoid RAM pressure.
_WORKER_COUNT = int(os.environ.get("WORKERS", str(min(8, _CPU_COUNT * 2))))
_IS_DEV       = os.environ.get("APP_ENV", "").lower() in ("development", "dev") \
                or os.environ.get("RELOAD", "false").lower() == "true"


# ── App lifecycle ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _lifespan(app: FastAPI):
    """
    On startup:
      1. Set a large thread pool executor (so sync analytics routes can run
         concurrently in threads without blocking the event loop).
      2. Warm the default asyncpg connection pool.
    On shutdown: close all per-database asyncpg pools gracefully.
    """
    import asyncio

    # ── 1. Thread pool (upgrade from Python's default of cpu+4 threads) ──────────
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(
        max_workers=_THREAD_POOL_SIZE,
        thread_name_prefix="dms_worker",
    )
    loop.set_default_executor(executor)
    logger.info(
        "\033[1;36m[STARTUP]\033[0m Thread pool initialized: \033[1;33m%d threads\033[0m "
        "(env: THREAD_POOL_SIZE=%d)",
        _THREAD_POOL_SIZE, _THREAD_POOL_SIZE,
    )

    # ── 2. asyncpg pool (default DB, warms on startup) ────────────────────────────
    try:
        from .async_db import init_pool, close_pool
        await init_pool()
        logger.info("\033[1;32m[STARTUP]\033[0m asyncpg default pool ready")
    except Exception as e:
        logger.warning(
            "\033[1;33m[STARTUP WARN]\033[0m asyncpg pool init failed (%s) — SQLAlchemy fallback active", e
        )

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────────
    try:
        from .async_db import close_pool
        await close_pool()
        logger.info("\033[1;33m[SHUTDOWN]\033[0m All asyncpg pools closed")
    except Exception:
        pass
    executor.shutdown(wait=False)
    logger.info("\033[1;33m[SHUTDOWN]\033[0m Thread pool shut down")


app = FastAPI(
    title="DMS Analytics",
    description="Distributor Management System — AI-powered analytics",
    version="1.0.0",
    lifespan=_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ── Enterprise CORS & Security Hardening ────────────────────────────────────
cors_origins_raw = os.environ.get("CORS_ORIGINS", "*").strip()
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    allow_origin_regex=r".*",
)


def is_detailed_error_logging_enabled() -> bool:
    val = os.environ.get("DETAILED_ERROR_LOGS", os.environ.get("DEBUG_LOGS", "true")).lower()
    return val in ("true", "1", "yes", "on", "debug")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Inject industry-standard OWASP security response headers and guarantee CORS headers."""
    from fastapi.responses import JSONResponse
    import traceback

    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            "\033[1;31m[HTTP UNHANDLED ERROR]\033[0m Path: %s | Error: %s",
            request.url.path, exc
        )
        if is_detailed_error_logging_enabled():
            logger.error(
                f"\n\033[1;31m{'='*25} [DETAILED HTTP ERROR TRACE] {'='*25}\033[0m\n"
                f"Path    : {request.url.path}\n"
                f"Method  : {request.method}\n"
                f"Headers : {dict(request.headers)}\n"
                f"Error   : {exc}\n"
                f"Traceback:\n{traceback.format_exc()}\n"
                f"\033[1;33m[TIP] Set DETAILED_ERROR_LOGS=false in .env to disable these verbose logs.\033[0m\n"
                f"\033[1;31m{'='*80}\033[0m\n"
            )
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error", "error": str(exc)},
        )

    origin = request.headers.get("origin") or "*"
    response.headers["Access-Control-Allow-Origin"] = origin
    if origin != "*":
        response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def log_incoming_request(request: Request, call_next):
    """Log every request immediately, enforce auth with proper CORS on failure."""
    t0 = time.time()
    origin = request.headers.get("origin") or "*"

    # ── Log EVERY request as soon as it arrives ────────────────────────────────
    session_uid = request.headers.get("x-uid") or request.headers.get("x_uid") or ""
    staff_uid = request.headers.get("u-uid") or request.headers.get("x-staff-uid") or request.headers.get("x_staff_uid") or ""
    connected_staff = None
    if request.url.path == "/api/prefs/output-lang" and session_uid and not staff_uid:
        try:
            from .services.database import get_session_staff_uid
            connected_staff = get_session_staff_uid(session_uid)
        except Exception:
            pass

    staff_display = staff_uid or (f"RESOLVED({connected_staff})" if connected_staff else "MISSING")

    logger.info(
        "\033[1;34m[REQUEST ▶]\033[0m %s %s | x-uid=%s | u-uid=%s | x-staff-uid=%s | origin=%s",
        request.method,
        request.url.path,
        session_uid or "MISSING",
        request.headers.get("u-uid", "MISSING"),
        staff_display,
        origin,
    )

    # ── Skip auth for CORS preflight (OPTIONS) — browser never sends custom headers on preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    # ── Auth gate for protected /api routes ────────────────────────────────────
    if request.url.path.startswith("/api") and not is_public_path(request.url.path):
        try:
            is_pref_lang = (request.url.path == "/api/prefs/output-lang")
            identity = require_request_identity(request, allow_session_staff_resolution=is_pref_lang)
            request.state.identity = identity
        except Exception as exc:
            status = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "Authentication required")
            all_headers = dict(request.headers)
            logger.warning(
                "\033[1;33m[AUTH FAIL ✗]\033[0m %s %s → %d | reason: %s\n"
                "  All headers sent by client:\n%s",
                request.method, request.url.path, status, detail,
                "\n".join(f"    {k}: {v}" for k, v in all_headers.items()),
            )
            # IMPORTANT: include CORS headers so browser shows 401, NOT a fake CORS error
            resp = JSONResponse(status_code=status, content={"detail": detail})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Methods"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "*"
            return resp

    user_id = (
        (getattr(getattr(request, "state", None), "identity", None) and request.state.identity.staff_uid)
        or staff_uid
        or connected_staff
        or session_uid
        or request.headers.get("x-user-id")
        or request.headers.get("userid")
        or request.query_params.get("userid")
        or request.query_params.get("user_id")
        or request.query_params.get("uid")
    )
    user_id_str = str(user_id).strip() if user_id else "Anonymous"
    token = current_user_id.set(user_id_str)

    try:
        response = await call_next(request)
        elapsed_ms = (time.time() - t0) * 1000
        logger.info(
            "\033[1;32m[RESPONSE ◀]\033[0m %s %s → %d | %.1fms | uid=%s",
            request.method, request.url.path,
            response.status_code, elapsed_ms, user_id_str,
        )
        return response
    except Exception as exc:
        logger.error(
            "\033[1;31m[REQUEST ERROR]\033[0m %s %s | %s | %.1fms | uid=%s",
            request.method, request.url.path, exc,
            (time.time() - t0) * 1000, user_id_str,
            exc_info=True,
        )
        raise
    finally:
        current_user_id.reset(token)


# Include routers
app.include_router(main_router)
app.include_router(analytics_router)
app.include_router(chat_router)
app.include_router(staff_router)
app.include_router(export_router)
app.include_router(database_router)
app.include_router(speech_router)
app.include_router(prefs_router)

# Mount static files
if settings.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")

# Mount React chat app
_chat_dir = settings.BASE_DIR / "app" / "chat_react"
if _chat_dir.exists():
    app.mount("/chat/static", StaticFiles(directory=str(_chat_dir)), name="chat_react_static")

@app.get("/chat", include_in_schema=False)
async def serve_chat_react():
    idx = _chat_dir / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": "chat_react/index.html not found"}, status_code=503)


def main():
    host    = settings.HOST
    port    = settings.PORT
    gemini  = "OK" if settings.has_gemini_key() else "NOT SET"
    mode    = "development (reload)" if _IS_DEV else f"production ({_WORKER_COUNT} workers)"

    print(f"""
+------------------------------------------------------+
|        DMS Analytics -- AI-Powered Platform          |
+------------------------------------------------------+
|  Server:  http://{host}:{port}
|  Docs:    http://{host}:{port}/docs
|  Gemini:  {gemini}
|  Mode:    {mode}
|  Threads: {_THREAD_POOL_SIZE} per worker
+------------------------------------------------------+
""")

    if _IS_DEV:
        # Development: single worker + hot reload
        uvicorn.run("app.main:app", host=host, port=port, reload=True)
    else:
        # Production: multiple workers, no reload
        # Each worker = independent process with its own thread pool + asyncpg pools
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            workers=_WORKER_COUNT,
            loop="uvloop",       # faster event loop (install: pip install uvloop)
            http="httptools",    # faster HTTP parser (install: pip install httptools)
            access_log=False,    # disable per-request access logs for performance
            timeout_keep_alive=30,
        )


if __name__ == "__main__":
    main()
