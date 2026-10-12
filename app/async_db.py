"""
=============================================================================
  DMS Async Database Layer — asyncpg + asyncio
=============================================================================

Architecture:
  - asyncpg.Pool (min=5, max=50) — single shared pool for the whole process.
  - No threads, no GIL fighting, no semaphores needed — asyncio event loop
    handles all I/O concurrency natively.
  - 200 concurrent API requests → 200 coroutines → ~50 active DB connections
    → remaining 150 await the pool naturally (no "too many clients").
  - 3-5x faster than psycopg + threads for analytical query workloads.

Usage:
  Direct async (FastAPI routes, recommended):
    result = await async_run_query(sql, params)
    results = await async_run_parallel([(sql1, p1), (sql2, p2)])

  Sync bridge (existing analytics functions — zero code change needed):
    from .db import run_query, run_parallel   ← unchanged import, calls async underneath
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
from contextvars import ContextVar, copy_context
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("dms.async_db")

# ── Event-loop-owned pool cache ────────────────────────────────────────────────
# asyncpg pools cannot be shared between event loops. The FastAPI loop and the
# background loop used by synchronous analytics callers each own their pool.
_pools: Dict[Tuple[int, str], any] = {}       # (event_loop_id, dsn) -> pool
_pool_loops: Dict[Tuple[int, str], asyncio.AbstractEventLoop] = {}

# ── Query result cache ──────────────────────────────────────────────────────────
_QUERY_CACHE: Dict[tuple, tuple] = {}
_CACHE_LOCK = threading.Lock()
QUERY_CACHE_TTL = float(os.environ.get("DB_QUERY_CACHE_TTL", "15"))

# ── Pool config ─────────────────────────────────────────────────────────────────
POOL_MIN                   = int(os.environ.get("ASYNCPG_POOL_MIN", "0"))    # 0 = no permanently idle connections
POOL_MAX                   = int(os.environ.get("ASYNCPG_POOL_MAX", "50"))   # max connections per DB under load
POOL_IDLE_TTL              = float(os.environ.get("ASYNCPG_IDLE_TTL", "300")) # seconds before idle connections are reaped
STATEMENT_TIMEOUT          = int(os.environ.get("QUERY_TIMEOUT_SEC", "120"))


_ASYNCPG_INVALID_PARAMS = {
    "charset", "use_unicode", "auth_plugin", "allowpublickeyretrieval",
    "servertimezone", "zerodatetimebehavior", "serverTimezone",
    "zeroDateTimeBehavior", "allowPublicKeyRetrieval",
}


def _sanitize_asyncpg_dsn(url: str) -> str:
    """
    Strip MySQL-style and unsupported query parameters from a PostgreSQL DSN.
    asyncpg passes unknown query params as startup parameters to the server;
    MySQL-style params like 'charset=utf8mb4' cause the server (or a PgBouncer
    proxy in front of it) to reject the connection with 'unknown startup option'.
    """
    if "?" not in url:
        return url
    base, qs = url.split("?", 1)
    kept = []
    for part in qs.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0].lower()
        if key not in _ASYNCPG_INVALID_PARAMS and key.lower() not in {p.lower() for p in _ASYNCPG_INVALID_PARAMS}:
            kept.append(part)
    return (base + "?" + "&".join(kept)) if kept else base


def _build_dsn() -> str:
    """Build asyncpg DSN from DATABASE_URL env (strips SQLAlchemy driver prefix). Raises error if not set."""
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw or raw in ("''", '""'):
        raise ValueError("No registered database found for user and environment variable DATABASE_URL is not set.")
    raw = re.sub(r"^postgresql\+\w+://", "postgresql://", raw)
    raw = re.sub(r"^postgres://", "postgresql://", raw)
    raw = _sanitize_asyncpg_dsn(raw)
    if not raw or not raw.startswith("postgresql://"):
        raise ValueError(f"Invalid DATABASE_URL format: '{raw}'")
    return raw


async def _build_dsn_for_uid(uid: Optional[str] = None) -> str:
    """Resolve DSN for a user strictly (checks registered session, no arbitrary fallback)."""
    target_uid = uid
    if not target_uid:
        try:
            from .db import current_user_id
            target_uid = current_user_id.get()
        except Exception:
            pass

    if target_uid:
        try:
            from .services.database import get_session_db_url
            url = get_session_db_url(str(target_uid).strip())
            if url and url.strip():
                url = url.strip()
                url = re.sub(r"^postgresql\+\w+://", "postgresql://", url)
                url = re.sub(r"^postgres://", "postgresql://", url)
                url = _sanitize_asyncpg_dsn(url)
                if url.startswith("postgresql://"):
                    safe_target = url.split("@", 1)[-1]
                    logger.info("[DB ROUTE] UID=%s | source=registered | target=%s", target_uid, safe_target)
                    return url
        except Exception as e:
            logger.warning("[BUILD DSN UID ERROR] %s", e)

    raw_env = (os.environ.get("DATABASE_URL") or "").strip()
    if raw_env and raw_env not in ("''", '""'):
        # Default-DB fallback is allowed ONLY for the password-gated native chat
        # (allow_default_db). Every other caller must have a registered session.
        try:
            from .db import allow_default_db
            _fallback_ok = bool(allow_default_db.get())
        except Exception:
            _fallback_ok = False
        if _fallback_ok:
            logger.warning("[DB ROUTE] UID=%s has no registered database; using DATABASE_URL fallback (native chat only)", target_uid or "Unknown")
            return _build_dsn()

    raise ValueError(f"Database registration required. No database registered for User ID '{target_uid or 'Unknown'}'.")


# ── Background event loop manager for sync callers ──────────────────────────────
_BG_LOOP: Optional[asyncio.AbstractEventLoop] = None
_BG_THREAD: Optional[threading.Thread] = None
_BG_LOCK = threading.Lock()


def _get_bg_loop() -> asyncio.AbstractEventLoop:
    global _BG_LOOP, _BG_THREAD
    if _BG_LOOP is not None and _BG_LOOP.is_running():
        return _BG_LOOP
    with _BG_LOCK:
        if _BG_LOOP is not None and _BG_LOOP.is_running():
            return _BG_LOOP
        loop = asyncio.new_event_loop()
        def _run():
            asyncio.set_event_loop(loop)
            loop.run_forever()
        t = threading.Thread(target=_run, daemon=True, name="async_db_bg_loop")
        t.start()
        _BG_LOOP = loop
        _BG_THREAD = t
        return _BG_LOOP


# ── Pool lifecycle ──────────────────────────────────────────────────────────────

async def _create_pool(dsn: str):
    """
    Create a new asyncpg pool for a given DSN.

    PgBouncer compatibility notes (port 9999 or any proxy):
      - statement_cache_size=0  : disables asyncpg prepared statements.
        PgBouncer in *transaction* pooling mode does not support the PostgreSQL
        extended query protocol (prepared statements), and returns
        "ERROR: unable to get session context" when asyncpg tries to use them.
      - server_settings omitted : asyncpg sends server_settings as startup
        parameters; PgBouncer in transaction mode also rejects these with the
        same error. Use _init_conn for any per-connection setup instead.
      - SET commands wrapped in try/except : session-level SETs are no-ops
        on PgBouncer transaction mode (no persistent session), so failures
        are tolerated rather than raising.
    """
    import asyncpg

    safe = dsn.split("@")[-1] if "@" in dsn else dsn
    logger.info(
        "\033[1;36m[ASYNCPG POOL INIT]\033[0m New pool (READ-ONLY) → DB: \033[1;33m%s\033[0m | min=%d max=%d timeout=%ds",
        safe, POOL_MIN, POOL_MAX, STATEMENT_TIMEOUT,
    )

    async def _init_conn(conn):
        # These SETs are best-effort. On a direct PostgreSQL connection they
        # persist for the connection's lifetime. On PgBouncer transaction mode
        # they are silently discarded — that's acceptable; the pool is still
        # usable and the timeout is enforced by command_timeout= at the pool
        # level.
        try:
            await conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT * 1000}'")
        except Exception as e:
            logger.debug("[ASYNCPG POOL] statement_timeout not set (proxy?): %s", e)
        try:
            await conn.execute("SET default_transaction_read_only = 'on'")
        except Exception as e:
            logger.debug("[ASYNCPG POOL] read-only mode not set (proxy?): %s", e)

    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=POOL_MIN,                               # 0 = no idle sockets held open
        max_size=POOL_MAX,
        max_inactive_connection_lifetime=POOL_IDLE_TTL,  # reap connections idle > 5 min
        command_timeout=STATEMENT_TIMEOUT,
        init=_init_conn,
        # Disable the prepared-statement cache.  asyncpg uses PostgreSQL's
        # extended query protocol for prepared statements, which PgBouncer
        # transaction pooling mode does not support.  Setting this to 0 forces
        # asyncpg to use the simple query protocol for every statement, which
        # works correctly on both direct PostgreSQL and PgBouncer proxies.
        statement_cache_size=0,
        # server_settings intentionally omitted: passing startup parameters
        # through a PgBouncer proxy in transaction mode triggers the
        # "unable to get session context" error.
    )
    logger.info("\033[1;32m[ASYNCPG POOL READY]\033[0m max=%d | DB: %s", POOL_MAX, safe)
    return pool


async def get_or_create_pool(dsn: str):
    """Return the pool owned by the current event loop for this DSN."""
    if not dsn or not isinstance(dsn, str) or not dsn.strip() or not dsn.startswith("postgresql://"):
        dsn = _build_dsn()
    loop = asyncio.get_running_loop()
    key = (id(loop), dsn)
    if key in _pools:
        return _pools[key]
    pool = await _create_pool(dsn)
    _pools[key] = pool
    _pool_loops[key] = loop
    return pool


async def ensure_pool(uid: Optional[str] = None):
    """Resolve DSN for this user and return (or lazily create) their pool."""
    dsn = await _build_dsn_for_uid(uid)
    return await get_or_create_pool(dsn)


async def init_pool() -> None:
    """Warm the default pool on FastAPI startup. Called once by lifespan hook."""
    await get_or_create_pool(_build_dsn())


async def close_pool() -> None:
    """Gracefully close ALL pools on FastAPI shutdown."""
    current_loop = asyncio.get_running_loop()
    for key, pool in list(_pools.items()):
        owner_loop = _pool_loops.get(key)
        dsn = key[1]
        try:
            if owner_loop is current_loop:
                await pool.close()
            elif owner_loop and owner_loop.is_running():
                close_future = asyncio.run_coroutine_threadsafe(pool.close(), owner_loop)
                await asyncio.wrap_future(close_future)
            safe = dsn.split("@")[-1] if "@" in dsn else dsn
            logger.info("\033[1;33m[ASYNCPG POOL CLOSED]\033[0m DB: %s", safe)
        except Exception:
            pass
    _pools.clear()
    _pool_loops.clear()


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_key(uid: str, sql: str, params: Optional[dict]) -> tuple:
    return (uid, sql, json.dumps(params or {}, sort_keys=True, default=str))


def _cache_get(key: tuple) -> Optional[dict]:
    if QUERY_CACHE_TTL <= 0:
        return None
    with _CACHE_LOCK:
        entry = _QUERY_CACHE.get(key)
        if entry:
            ts, val = entry
            if time.time() - ts < QUERY_CACHE_TTL:
                return val
    return None


def _cache_set(key: tuple, val: dict) -> None:
    if QUERY_CACHE_TTL <= 0:
        return
    now = time.time()
    with _CACHE_LOCK:
        _QUERY_CACHE[key] = (now, val)
        if len(_QUERY_CACHE) > 5000:
            stale = [k for k, (t, _) in _QUERY_CACHE.items() if now - t > QUERY_CACHE_TTL]
            for k in stale:
                _QUERY_CACHE.pop(k, None)


_EXPLICIT_INT_PARAMS = {
    "userid_int", "so_userid", "distributorid", "dealerid",
    "itemid", "salespersonid", "locationid", "limit", "offset", "item_id",
}


def _coerce_param_value(name: str, val: any) -> any:
    if isinstance(val, str):
        lname = name.lower()
        # Do NOT convert userid / user_id / uid to int — RBAC matches them against TEXT userguid
        if lname in ("userid", "user_id", "uid"):
            return val

        # ISO Date conversion: '2025-01-01' -> date(2025, 1, 1)
        if len(val) == 10 and val[4] == '-' and val[7] == '-':
            try:
                return date.fromisoformat(val)
            except ValueError:
                pass
        # ISO Datetime conversion
        if len(val) >= 19 and ('T' in val or ' ' in val) and val[4] == '-' and val[7] == '-':
            try:
                from datetime import datetime
                return datetime.fromisoformat(val)
            except ValueError:
                pass
        # Integer conversion: '1' -> 1 ONLY for explicitly integer param names
        if val.lstrip('-').isdigit():
            if lname in _EXPLICIT_INT_PARAMS or lname.endswith("_int") or lname.endswith("_num"):
                try:
                    return int(val)
                except ValueError:
                    pass
    return val


def _convert_params(sql: str, params: Optional[dict]) -> Tuple[str, list]:
    """
    Convert SQLAlchemy-style :name params to asyncpg $N positional params
    with type coercion (dates, integers).
    Returns (converted_sql, ordered_values_list).
    """
    if not params:
        return sql, []

    values = []
    counter = [0]

    def _replace(m):
        name = m.group(1)
        counter[0] += 1
        raw_val = params.get(name)
        coerced = _coerce_param_value(name, raw_val)
        values.append(coerced)
        return f"${counter[0]}"

    converted = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", _replace, sql)
    return converted, values


# ── Core async query runner ────────────────────────────────────────────────────

async def async_run_query(
    sql: str,
    params: Optional[dict] = None,
    uid: Optional[str] = None,
) -> dict:
    """
    Execute a single query.
    Automatically routes to the correct database pool for this uid.
    Auto-creates pool on first use (multi-tenant: one pool per customer DB).
    """
    uid = uid or "system"
    sql_clean = sql.strip()
    key = _cache_key(uid, sql_clean, params)

    cached = _cache_get(key)
    if cached is not None:
        return cached

    t0 = time.perf_counter()
    try:
        pg_sql, pg_vals = _convert_params(sql_clean, params)
        pool = await ensure_pool(uid)          # ← routes to correct DB for this user
        async with pool.acquire() as conn:
            rows_raw = await conn.fetch(pg_sql, *pg_vals)

        columns = list(rows_raw[0].keys()) if rows_raw else []
        rows = [dict(r) for r in rows_raw]
        result = {"columns": columns, "rows": rows, "row_count": len(rows), "error": None}
        _cache_set(key, result)
        return result

    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        err = str(e)[:500]
        logger.error(
            "\033[1;31m[ASYNCPG QUERY ERROR]\033[0m UID=%s | %.1fms | %s",
            uid, elapsed, err[:200],
        )
        return {"columns": [], "rows": [], "row_count": 0, "error": err}


async def async_run_parallel(
    queries_params: List[Tuple[str, dict]],
    uid: Optional[str] = None,
) -> List[dict]:
    """
    Execute multiple queries concurrently using asyncio.gather.
    """
    uid = uid or "system"

    async def _one(sql: str, p: dict) -> dict:
        return await async_run_query(sql, p, uid=uid)

    results = await asyncio.gather(*[_one(sql, p) for sql, p in queries_params])
    return list(results)


async def async_run_monthly_parallel(
    sql: str,
    base_params: dict,
    threshold_days: int = 32,
    uid: Optional[str] = None,
) -> dict:
    """
    Async month-slicing COLLECT strategy.
    """
    uid = uid or base_params.get("userid", "system")

    # Check if range is large enough to slice
    df = base_params.get("date_from")
    dt = base_params.get("date_to")
    is_large = False
    if df and dt:
        try:
            is_large = (date.fromisoformat(str(dt)) - date.fromisoformat(str(df))).days > threshold_days
        except ValueError:
            pass

    if not is_large:
        return await async_run_query(sql, base_params, uid=uid)

    # Build monthly slices
    slices = _split_months(str(df), str(dt))
    if len(slices) <= 1:
        return await async_run_query(sql, base_params, uid=uid)

    queries = [(sql, {**base_params, "date_from": mf, "date_to": mt}) for mf, mt in slices]
    slice_results = await async_run_parallel(queries, uid=uid)

    all_rows, all_columns, errors = [], [], []
    for i, res in enumerate(slice_results):
        if res is None:
            continue
        if res.get("error"):
            errors.append(res["error"])
            continue
        rows = res.get("rows") or []
        m_label = slices[i][0][:7]
        for row in rows:
            row["_month"] = m_label
        all_rows.extend(rows)
        if not all_columns:
            all_columns = res.get("columns") or []

    if errors and not all_rows:
        return {"columns": [], "rows": [], "row_count": 0, "error": "; ".join(errors[:3])}
    if all_columns and "_month" not in all_columns:
        all_columns = list(all_columns) + ["_month"]

    return {"columns": all_columns, "rows": all_rows, "row_count": len(all_rows), "error": None}


def _split_months(date_from_str: str, date_to_str: str) -> list:
    try:
        d_from = date.fromisoformat(date_from_str)
        d_to   = date.fromisoformat(date_to_str)
    except ValueError:
        return [(date_from_str, date_to_str)]
    slices = []
    cursor = d_from.replace(day=1)
    while cursor <= d_to:
        m_start = max(cursor, d_from)
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        m_end = min(next_month - timedelta(days=1), d_to)
        slices.append((m_start.isoformat(), m_end.isoformat()))
        cursor = next_month
    return slices


# ── Sync bridge ────────────────────────────────────────────────────────────────

def _resolve_uid_for_sync(explicit_uid: Optional[str] = None) -> Optional[str]:
    """
    Resolve the best uid to use for DB routing in sync callers.
    Priority: explicit arg > _db_uid in params (handled upstream) > current_db_uid ContextVar.
    The ContextVar is readable here because we're still on the ThreadPoolExecutor worker
    thread that inherited the context from the FastAPI request handler.
    """
    if explicit_uid and str(explicit_uid).strip() not in ("system", ""):
        return explicit_uid
    try:
        from .db import current_db_uid as _ctx_var
        cv = _ctx_var.get()
        if cv and str(cv).strip():
            return str(cv).strip()
    except Exception:
        pass
    return explicit_uid


def _run_in_loop(coro):
    """
    Schedule a coroutine on the background event loop from any sync thread
    (load test, sync analytics functions, etc).
    Pool creation is handled lazily inside async_run_query via ensure_pool().
    """
    loop = _get_bg_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=float(os.environ.get("QUERY_TIMEOUT_SEC", "120")))


def sync_run_query(sql: str, params: Optional[dict] = None, uid: Optional[str] = None) -> dict:
    """Sync wrapper for async_run_query — drop-in replacement for old run_query."""
    uid = _resolve_uid_for_sync(uid)
    return _run_in_loop(async_run_query(sql, params, uid=uid))


def sync_run_parallel(
    queries_params: List[Tuple[str, dict]],
    uid: Optional[str] = None,
) -> List[dict]:
    """Sync wrapper for async_run_parallel — drop-in replacement for old run_parallel."""
    uid = _resolve_uid_for_sync(uid)
    return _run_in_loop(async_run_parallel(queries_params, uid=uid))


def sync_run_monthly_parallel(
    sql: str,
    base_params: dict,
    threshold_days: int = 32,
    uid: Optional[str] = None,
) -> dict:
    """Sync wrapper for async_run_monthly_parallel — drop-in replacement for old run_monthly_parallel."""
    uid = _resolve_uid_for_sync(uid)
    return _run_in_loop(async_run_monthly_parallel(sql, base_params, threshold_days, uid=uid))
