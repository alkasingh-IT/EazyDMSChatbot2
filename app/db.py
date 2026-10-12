"""
Database connection management for DMS Analytics.

Primary path  : asyncpg pool (async_db.py) — true async I/O, no GIL fighting.
                run_query / run_parallel / run_monthly_parallel delegate here
                via sync bridge wrappers so all existing analytics code is
                unchanged.
Fallback path : SQLAlchemy + psycopg (used only for get_engine() callers that
                need a raw Engine object, e.g. legacy admin scripts).
"""
import os
import re
import time
import json
import logging
import threading
from typing import Optional, List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine

# ── asyncpg sync bridges (zero-change drop-in for all analytics callers) ──────
try:
    from .async_db import (
        sync_run_query        as _async_run_query,
        sync_run_parallel     as _async_run_parallel,
        sync_run_monthly_parallel as _async_run_monthly_parallel,
    )
    _USE_ASYNCPG = True
except Exception as _e:
    _USE_ASYNCPG = False
    logging.getLogger("dms.db").warning(
        "[DB] asyncpg layer unavailable (%s) — falling back to SQLAlchemy/psycopg", _e
    )

logger = logging.getLogger("dms.db")

current_user_id: ContextVar[Optional[str]] = ContextVar("current_user_id", default=None)
# Per-request DB routing override — set before calling analytics functions so every
# internal run_query call routes to the correct registered DB without needing _db_uid in params.
current_db_uid: ContextVar[Optional[str]] = ContextVar("current_db_uid", default=None)
# When True, a request with NO registered session DB may fall back to DATABASE_URL.
# ONLY the password-gated native chat sets this. The general app must never fall
# back — a missing session there is an error, not a silent default.
allow_default_db: ContextVar[bool] = ContextVar("allow_default_db", default=False)

_engines_cache: Dict[str, Engine] = {}
_engine_lock = threading.Lock()

# ── Connection concurrency guard ──────────────────────────────────────────────
# Pool size (30) + overflow (20) = 50 max live PG connections per process.
# This semaphore enforces the same cap BEFORE acquiring from the pool,
# preventing QueuePool timeouts and "too many clients" under 200-concurrent load.
# 200 concurrent API threads → 50 run DB queries → 150 wait here (not at PG).
_DB_POOL_CAP     = int(os.environ.get("DB_POOL_CAP", "50"))   # must equal pool_size + max_overflow
_APP_DB_SEMAPHORE = threading.Semaphore(_DB_POOL_CAP)

# Ultra High-Speed Query Result Cache: { (uid, sql, frozen_params) -> (timestamp, result_dict) }
_QUERY_CACHE: Dict[tuple, tuple] = {}
_CACHE_LOCK = threading.Lock()
QUERY_CACHE_TTL = float(os.environ.get("DB_QUERY_CACHE_TTL", "15"))  # 15s TTL for analytical queries
STATEMENT_TIMEOUT_MS = int(os.environ.get("QUERY_TIMEOUT_SEC", "120")) * 1000



def _extract_user_id(params: Optional[dict] = None) -> str:
    """Resolve database registration identity separately from SQL userid."""
    # 1. Explicit override in params — highest priority
    if params and params.get("_db_uid"):
        return str(params["_db_uid"])
    # 2. Per-request DB routing context (set by chat/analytics routes before running flags)
    #    This propagates to worker threads because ThreadPoolExecutor copies the context.
    db_uid_ctx = current_db_uid.get()
    if db_uid_ctx and str(db_uid_ctx).strip():
        logger.debug("[DB ROUTE] Using current_db_uid context: %s", db_uid_ctx)
        return str(db_uid_ctx).strip()
    # 3. Fallback: userid in params (direct API calls without session registration)
    if params:
        for k in ("userid", "user_id", "uid", "so_userid", "_userid"):
            if params.get(k):
                return str(params.get(k))
    # 4. Request UID from middleware context
    ctx_uid = current_user_id.get()
    return str(ctx_uid) if ctx_uid else "System/Anonymous"


def _sql_params(params: Optional[dict]) -> dict:
    """Remove internal routing metadata before sending params to SQLAlchemy."""
    return {k: v for k, v in (params or {}).items() if k != "_db_uid"}


def _sanitize_db_url(db_url: str) -> str:
    """Sanitize database connection URL by normalizing drivers and stripping unsupported psycopg query parameters."""
    if not db_url:
        return db_url

    url = db_url.strip().strip("\"' \t\r\n")

    if "://undefined:" in url or "://undefined@" in url:
        logger.warning("\033[1;31m[DB CONFIG WARNING]\033[0m Registered Database URL contains username 'undefined'!")

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    invalid_params = ["charset", "use_unicode", "auth_plugin", "allowPublicKeyRetrieval", "serverTimezone", "zeroDateTimeBehavior"]
    for param in invalid_params:
        url = re.sub(rf'([?&]){param}=[^&]*(&|$)', r'\1', url, flags=re.IGNORECASE)

    url = re.sub(r'[?&]$', '', url)
    url = re.sub(r'\?&', '?', url)
    return url


def _get_cache_key(uid: str, sql: str, params: Optional[dict]) -> tuple:
    param_str = json.dumps(params or {}, sort_keys=True) if params else ""
    return (uid, sql, param_str)



def get_engine(uid: Optional[str] = None) -> Engine:
    """Get or create the SQLAlchemy engine for default DB or registered user session DB."""
    if not uid:
        uid = current_user_id.get()

    target_url = None
    is_registered = False
    if uid:
        try:
            from .services.database import get_session_db_url
            target_url = get_session_db_url(str(uid))
            if target_url:
                is_registered = True
        except Exception as e:
            logger.warning("Could not fetch session DB URL for UID %s: %s", uid, e)

    if not target_url:
        # Default-DB fallback is allowed ONLY for the password-gated native chat
        # (allow_default_db). Every other caller must have a registered session.
        if allow_default_db.get():
            target_url = (os.environ.get("DATABASE_URL", "") or "").strip()
            if target_url:
                logger.info("[DB ROUTE] No session DB — using default DATABASE_URL (native chat only)")
        else:
            target_url = ""

    if target_url.startswith("psql"):
        target_url = target_url[4:].strip().strip("\"' \t\r\n")

    if not target_url:
        raise ValueError(f"Database registration required. No database registered for user '{uid or 'Unknown'}'.")

    db_url = _sanitize_db_url(target_url)

    # Fast path check without lock overhead when cached
    if db_url in _engines_cache:
        return _engines_cache[db_url]

    with _engine_lock:
        if db_url in _engines_cache:
            return _engines_cache[db_url]

        safe = db_url.split("@")[-1] if "://" in db_url else db_url
        logger.info("\033[1;36m[DB CONNECT ENGINE CREATION]\033[0m Target: postgresql://***:***@%s | User ID: %s | Registered Session: %s", safe, uid or "Default/System", is_registered)
        try:
            pool_size    = int(os.environ.get("DB_POOL_SIZE", "30"))
            max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "20"))
            pool_timeout = int(os.environ.get("DB_POOL_TIMEOUT", "120"))  # queue, don't crash

            # Build connect_args with TCP keepalives + read-only transaction mode
            connect_args: dict = {"options": "-c default_transaction_read_only=on"}
            if "psycopg" in db_url:
                connect_args.update({
                    "connect_timeout": 10,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 5,
                    "keepalives_count": 5,
                })

            engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=1800,
                pool_reset_on_return="rollback",
                connect_args=connect_args,
                execution_options={"isolation_level": "AUTOCOMMIT"},
            )
            
            @event.listens_for(engine, "connect")
            def _set_read_only(dbapi_connection, connection_record):
                try:
                    cursor = dbapi_connection.cursor()
                    cursor.execute("SET default_transaction_read_only = 'on'")
                    cursor.close()
                except Exception:
                    pass

            logger.info(
                "\033[1;32m[DB POOL CREATED]\033[0m pool_size=%d max_overflow=%d pool_timeout=%ds (READ-ONLY)",
                pool_size, max_overflow, pool_timeout,
            )
            _engines_cache[db_url] = engine
            return engine
        except Exception as e:
            logger.error("\033[1;31m[DB ENGINE FAIL]\033[0m Engine creation failed for %s: %s", safe, str(e)[:500])
            raise


def run_query(sql: str, params: dict) -> dict:
    """
    Execute a parameterized query.

    Primary path  (asyncpg):  True async I/O via the shared asyncpg pool.
                              200 concurrent callers → 50 active DB connections
                              → 150 coroutines awaiting a pool slot.
                              No threads, no GIL, no "too many clients".

    Fallback path (SQLAlchemy): Used only if asyncpg pool is not initialized.
    """
    if _USE_ASYNCPG:
        uid = _extract_user_id(params)
        return _async_run_query(sql, params, uid=uid)

    # ── SQLAlchemy fallback (semaphore-guarded) ──────────────────────────────
    t0 = time.time()
    uid = _extract_user_id(params)
    sql_clean = sql.strip().replace("\r\n", "\n").replace("\r", "\n")

    cache_key = _get_cache_key(uid, sql_clean, params)
    now = time.time()
    if QUERY_CACHE_TTL > 0:
        with _CACHE_LOCK:
            if cache_key in _QUERY_CACHE:
                ts, cached_res = _QUERY_CACHE[cache_key]
                if now - ts < QUERY_CACHE_TTL:
                    return cached_res

    acquired = _APP_DB_SEMAPHORE.acquire(timeout=float(os.environ.get("DB_POOL_TIMEOUT", "120")))
    if not acquired:
        return {"columns": [], "rows": [], "row_count": 0,
                "error": "DB connection pool exhausted — too many concurrent requests."}
    try:
        engine = get_engine(uid)
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT",
            postgresql_statement_timeout=STATEMENT_TIMEOUT_MS,
        ) as conn:
            result = conn.execute(text(sql_clean), _sql_params(params))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        res_dict = {"columns": columns, "rows": rows, "row_count": len(rows), "error": None}
        if QUERY_CACHE_TTL > 0:
            with _CACHE_LOCK:
                _QUERY_CACHE[cache_key] = (now, res_dict)
        return res_dict
    except Exception as e:
        return {"columns": [], "rows": [], "row_count": 0, "error": str(e)[:500]}
    finally:
        _APP_DB_SEMAPHORE.release()



def run_parallel(queries_params: List[Tuple[str, dict]], max_workers: int = 12) -> List[dict]:
    """
    Run multiple queries concurrently.

    Primary path (asyncpg): asyncio.gather — true async, no threads.
    Fallback path (SQLAlchemy): semaphore-guarded ThreadPoolExecutor.
    """
    if _USE_ASYNCPG:
        uid = _extract_user_id(queries_params[0][1] if queries_params else None)
        return _async_run_parallel(queries_params, uid=uid)

    # ── SQLAlchemy fallback ──────────────────────────────────────────────────
    t0 = time.time()
    uid = _extract_user_id(queries_params[0][1] if queries_params else None)
    engine = get_engine(uid)
    effective_workers = min(max_workers, len(queries_params), _DB_POOL_CAP)

    def _run(sql: str, params: dict) -> dict:
        acquired = _APP_DB_SEMAPHORE.acquire(timeout=float(os.environ.get("DB_POOL_TIMEOUT", "120")))
        if not acquired:
            return {"columns": [], "rows": [], "row_count": 0,
                    "error": "DB connection pool exhausted during parallel slice execution."}
        try:
            with engine.connect().execution_options(
                isolation_level="AUTOCOMMIT",
                postgresql_statement_timeout=STATEMENT_TIMEOUT_MS,
            ) as conn:
                result = conn.execute(text(sql), _sql_params(params))
                cols = list(result.keys())
                rows = [dict(zip(cols, row)) for row in result.fetchall()]
            return {"columns": cols, "rows": rows, "row_count": len(rows), "error": None}
        except Exception as e:
            return {"columns": [], "rows": [], "row_count": 0, "error": str(e)[:500]}
        finally:
            _APP_DB_SEMAPHORE.release()

    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = {pool.submit(_run, sql, p): i for i, (sql, p) in enumerate(queries_params)}
        results = [None] * len(queries_params)
        for f in as_completed(futures):
            results[futures[f]] = f.result()

    elapsed = time.time() - t0
    logger.info(
        "\033[1;32m[DB PARALLEL SUCCESS]\033[0m Executed %d parallel queries in \033[1;32m%.3fs\033[0m | User ID: %s",
        len(results), elapsed, uid
    )
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  Month-Slice Parallel Query Executor  (COLLECT strategy)
# ─────────────────────────────────────────────────────────────────────────────

def _split_into_months(date_from_str: str, date_to_str: str) -> list:
    """Split a date range into calendar month slices. Returns list of (date_from, date_to) strings."""
    from datetime import date, timedelta
    try:
        d_from = date.fromisoformat(date_from_str)
        d_to   = date.fromisoformat(date_to_str)
    except ValueError:
        return [(date_from_str, date_to_str)]

    slices = []
    cursor = d_from.replace(day=1)
    while cursor <= d_to:
        # start of this month slice
        m_start = max(cursor, d_from)
        # end of this month slice (last day of month)
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        m_end = min(next_month - timedelta(days=1), d_to)
        slices.append((m_start.isoformat(), m_end.isoformat()))
        cursor = next_month
    return slices


def is_large_range(params: dict, threshold_days: int = 32) -> bool:
    """Returns True if the date range in params exceeds threshold_days."""
    from datetime import date, timedelta
    df = params.get("date_from")
    dt = params.get("date_to")
    if not df or not dt:
        return False
    try:
        return (date.fromisoformat(str(dt)) - date.fromisoformat(str(df))).days > threshold_days
    except ValueError:
        return False


def run_monthly_parallel(sql: str, base_params: dict, threshold_days: int = 32) -> dict:
    """
    COLLECT strategy: month-slice parallelism.

    Primary path (asyncpg): asyncio.gather — true async.
    Fallback path (SQLAlchemy): semaphore-guarded ThreadPoolExecutor.
    """
    if _USE_ASYNCPG:
        uid = _extract_user_id(base_params)
        return _async_run_monthly_parallel(sql, base_params, threshold_days, uid=uid)

    # ── SQLAlchemy fallback (original logic, kept intact) ────────────────────
    if not is_large_range(base_params, threshold_days):
        return run_query(sql, base_params)
    date_from = str(base_params.get("date_from", ""))
    date_to   = str(base_params.get("date_to", ""))
    slices    = _split_into_months(date_from, date_to)
    if len(slices) <= 1:
        return run_query(sql, base_params)
    queries = [(sql, {**base_params, "date_from": mf, "date_to": mt}) for mf, mt in slices]
    uid = _extract_user_id(base_params)
    logger.info(
        "\033[1;36m[MONTHLY PARALLEL FALLBACK]\033[0m %d slices | UID: %s",
        len(slices), uid
    )
    slice_results = run_parallel(queries, max_workers=min(12, len(slices)))
    all_rows, all_columns, total_rows, errors = [], [], 0, []
    for i, res in enumerate(slice_results):
        if res is None: continue
        if res.get("error"): errors.append(res["error"]); continue
        rows = res.get("rows") or []
        m_label = slices[i][0][:7]
        for row in rows: row["_month"] = m_label
        all_rows.extend(rows)
        if not all_columns: all_columns = res.get("columns") or []
        total_rows += len(rows)
    if errors and not all_rows:
        return {"columns": [], "rows": [], "row_count": 0, "error": "; ".join(errors[:3])}
    if all_columns and "_month" not in all_columns:
        all_columns = list(all_columns) + ["_month"]
    return {"columns": all_columns, "rows": all_rows, "row_count": total_rows, "error": None}


# Import needed inside run_monthly_parallel
from datetime import date  # noqa: E402
