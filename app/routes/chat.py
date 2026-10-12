import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
import json
import threading
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..db import run_query, current_db_uid, allow_default_db
from ..analytics import ALL_FLAGS
from ..services.chat import (
    generate_answer,
    generate_general_answer,
    get_scope_suggestions,
    route_question,
    suggest_chart,
    build_answer_prompts,
    _validate_shape_against_data,
    _log_shape_decision,
)
from ..services.llm import stream_oci_text, call_oci_text
from ..services.executive_report import (
    generate_executive_report,
    generate_bi_analysis,
    build_phase1_briefing,
    build_deterministic_chart_spec,
    handle_general_or_greeting,
    resolve_cross_questioning,
    _clean_markdown_formatting,
)
from ..services.chat_history import init_chat_history, list_sessions, save_turn
from ..services.user_prefs import UserPrefsService
from ..auth import require_request_identity

router = APIRouter(prefix="/api")
logger = logging.getLogger("dms.chat")
init_chat_history()

# Simple in-memory user profile cache: { userid -> (timestamp, profile_dict) }
_PROFILE_CACHE: Dict[str, tuple] = {}
_CACHE_TTL = 300 # 5 minutes

# Two-Phase Progressive Analytics — Job Cache (5-minute TTL, thread-safe)
_JOB_CACHE: Dict[str, Dict[str, Any]] = {}
_JOB_CACHE_LOCK = threading.Lock()
_JOB_CACHE_TTL = 300


def _job_cache_put(token: str, payload: dict) -> None:
    with _JOB_CACHE_LOCK:
        _JOB_CACHE[token] = {**payload, "_expires": time.time() + _JOB_CACHE_TTL}
        now = time.time()
        expired = [k for k, v in _JOB_CACHE.items() if v.get("_expires", 0) < now]
        for k in expired:
            _JOB_CACHE.pop(k, None)


def _job_cache_get(token: str) -> Optional[dict]:
    with _JOB_CACHE_LOCK:
        entry = _JOB_CACHE.get(token)
        if not entry:
            return None
        if entry.get("_expires", 0) < time.time():
            _JOB_CACHE.pop(token, None)
            return None
        return entry


def _chat_error_logs_enabled() -> bool:
    value = os.environ.get("CHAT_ERROR_LOGS", os.environ.get("DETAILED_ERROR_LOGS", "true"))
    return str(value).strip().lower() in {"1", "true", "yes", "on", "debug"}


def _log_chat_exception(event: str, exc: Exception, **context: Any) -> None:
    if not _chat_error_logs_enabled():
        return
    details = " | ".join(f"{key}={value}" for key, value in context.items())
    logger.exception("[CHAT ERROR] %s%s", event, f" | {details}" if details else "")


def _suggestions_block(suggestions: List[str]) -> str:
    """Deterministic markdown block appended to answers so suggestions ALWAYS appear."""
    if not suggestions:
        return ""
    lines = "\n".join(f"- {s}" for s in suggestions[:4])
    return f"\n\n**Try asking:**\n{lines}"


_SHAPE_DEFAULT = {"kind": "analytical", "reasoning": "", "upgraded": False}


def _explore_suggestions(
    kind: str,
    descriptions: List[tuple],
    scope_suggestions: List[str],
) -> List[str]:
    """
    Shape-aware follow-up chips for data answers (the "Explore further" layer).
    Deterministic question TEMPLATES per shape — they suggest what to ask next,
    they never state any data. Falls back to DB-probed scope suggestions for
    broad/no-data situations.
    """
    if kind == "lookup":
        return [
            "Show it distributor-wise",
            "Show it item-wise",
            "Compare it with the previous month",
            "Show the month-wise trend for the last 6 months",
        ]
    if kind == "comparison":
        return [
            "Show both sides distributor-wise",
            "Show both sides item-wise",
            "Which items drove the biggest change?",
            "Show the month-wise trend across both sides",
        ]
    if kind == "ranking":
        return [
            "Show the bottom performers",
            "Break down the leader item-wise",
            "Show the same ranking by quantity",
            "Compare the top two",
        ]
    if kind == "trend":
        return [
            "Show the same trend distributor-wise",
            "Show the same trend item-wise",
            "Compare the first and last month",
            "Show this month vs last month",
        ]
    return scope_suggestions or []


def _is_ai_analytics_enabled(request: Request, body_val: Optional[bool] = None) -> bool:
    """
    Check if AI analytics is enabled via mandatory HTTP header 'x-ai-analytics' (or 'ai-analytics').
    Rejects with 400 Bad Request if missing or invalid.
    """
    raw_header = request.headers.get("x-ai-analytics") or request.headers.get("ai-analytics")
    source = "header 'x-ai-analytics'"
    if raw_header is None and body_val is not None:
        raw_header = str(body_val)
        source = "body 'ai_analytics'"

    if raw_header is None or not str(raw_header).strip():
        logger.error("\033[1;31m[AI ANALYTICS]\033[0m Missing mandatory header 'x-ai-analytics'! Rejecting with 400.")
        raise HTTPException(
            status_code=400,
            detail="Missing required header: 'x-ai-analytics'. Must be 'true' (AI Narrative) or 'false' (Direct Executive BI)."
        )

    val = str(raw_header).strip().lower()
    if val in {"true", "1", "yes", "on"}:
        logger.info("\033[1;32m[AI ANALYTICS]\033[0m %s='%s' → ENABLED (LLM Narrative Analyst)", source, raw_header)
        return True
    elif val in {"false", "0", "no", "off"}:
        logger.info("\033[1;35m[AI ANALYTICS]\033[0m %s='%s' → DISABLED (High-Speed Direct Executive BI Engine)", source, raw_header)
        return False
    else:
        logger.error("\033[1;31m[AI ANALYTICS]\033[0m Invalid value %s='%s'! Rejecting with 400.", source, raw_header)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid value for header 'x-ai-analytics': '{raw_header}'. Must be 'true' or 'false'."
        )


class ChatRequest(BaseModel):
    userid: str = Field(..., max_length=128)
    message: Optional[str] = Field(default=None, max_length=4096)
    question: Optional[str] = Field(default=None, max_length=4096)
    history: Optional[List[Dict[str, Any]]] = Field(default=[], max_items=50)
    ai_analytics: Optional[bool] = Field(
        default=None,
        description="When False, executes high-speed deterministic executive BI engine instead of LLM analyst.",
    )
    name: Optional[str] = Field(default=None, max_length=256)
    designation: Optional[str] = Field(default=None, max_length=256)
    employee_code: Optional[str] = Field(default=None, max_length=128)
    username: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=256)
    mobile: Optional[str] = Field(default=None, max_length=64)
    session_id: Optional[str] = Field(default=None, max_length=128)
    # Two-phase progressive streaming
    phase: Optional[int] = Field(default=None)
    job_token: Optional[str] = Field(default=None)
    job_id: Optional[str] = Field(default=None)
    stream: Optional[bool] = Field(default=False)


def _history_uid(request: Request) -> str:
    return require_request_identity(request).session_uid


def _with_history(request: Request, req: ChatRequest, payload: Dict[str, Any]) -> Dict[str, Any]:
    uid = _history_uid(request)
    session_id = req.session_id or str(uuid.uuid4())
    resolved_q = req.message or req.question or ""
    data_snap = None
    if payload.get("rows") or payload.get("chart_spec"):
        data_snap = {
            "chartSpec": payload.get("chart_spec"),
            "cols": payload.get("columns") or [],
            "rows": (payload.get("rows") or [])[:50],
            "snapshotText": payload.get("flag_description") or "",
            "metricPills": [],
        }
    try:
        save_turn(uid, session_id, resolved_q, payload.get("answer", ""), data_snapshot=data_snap)
    except PermissionError as exc:
        logger.warning("Chat history owner mismatch for session UUID %s: %s", uid, exc)
    except Exception as exc:
        # History is best-effort — never fail the answer because of it.
        logger.exception("Chat history write failed for session UUID %s", uid)
    payload["session_id"] = session_id
    payload["history_saved"] = True
    return payload


def _get_staff_context(req: ChatRequest, staff_uid: Optional[str] = None) -> Dict[str, Any]:
    if req.name:
        return {
            "name": req.name,
            "designation": req.designation or "Staff member",
            "employee_code": req.employee_code or "",
            "username": req.username or "",
            "email": req.email or "",
            "mobile": req.mobile or "",
        }
    
    uid_key = str(staff_uid or req.userid)
    now = time.time()
    if uid_key in _PROFILE_CACHE:
        ts, cached_ctx = _PROFILE_CACHE[uid_key]
        if now - ts < _CACHE_TTL:
            return cached_ctx

    user_info = run_query("""
        SELECT
            COALESCE(e.employeename, u.description, u.username) AS name,
            COALESCE(d.designationname, 'Staff member') AS designation,
            COALESCE(e.employeecode, '') AS employee_code
        FROM sec_usermaster u
        LEFT JOIN hr_employeemaster e ON e.employeeid = u.employeeid
        LEFT JOIN designationmaster d ON d.designationid = e.designationid
        WHERE CAST(u.userguid AS TEXT) = CAST(:userid AS TEXT) OR CAST(u.id AS TEXT) = CAST(:userid AS TEXT) OR u.username = :userid
        LIMIT 1
    """, {"userid": uid_key})
    
    if user_info.get("rows") and len(user_info["rows"]) > 0:
        ctx = user_info["rows"][0]
    else:
        ctx = {"name": uid_key, "designation": "Staff member"}
    
    _PROFILE_CACHE[uid_key] = (now, ctx)
    return ctx



@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    SEP = "=" * 70
    logger.info("\033[1;36m%s\033[0m", SEP)
    logger.info("\033[1;36m[CHAT REQUEST RECEIVED]\033[0m")
    logger.info(" Headers : x-uid=%s | x-staff-uid=%s | x-ai-analytics=%s | origin=%s",
        request.headers.get("x-uid", "MISSING"),
        request.headers.get("x-staff-uid", "MISSING"),
        request.headers.get("x-ai-analytics") or request.headers.get("ai-analytics", "MISSING"),
        request.headers.get("origin", "-")
    )
    logger.info(" Payload : userid=%s | message='%s' | history_turns=%d | session_id=%s",
        req.userid, req.message, len(req.history or []), req.session_id
    )

    try:
        from ..services.native_gate import is_native_chat as _nc_is_native
    except ImportError:
        from services.native_gate import is_native_chat as _nc_is_native

    _is_native_req = _nc_is_native(request)
    if _is_native_req:
        # Password-gated native chat: no registered session required, and it is
        # the ONLY path allowed to use the default DATABASE_URL.
        staff_uid = (
            request.headers.get("u-uid")
            or request.headers.get("x-staff-uid")
            or request.headers.get("x_staff_uid")
            or req.userid
            or ""
        ).strip()
        history_uid = staff_uid or "default"
        allow_default_db.set(True)
        logger.info("\033[1;35m[CHAT AUTH]\033[0m Native chat (password-gated) — default DB | staff_uid=%s", staff_uid)
    else:
        try:
            identity = require_request_identity(request)
        except Exception as auth_exc:
            logger.error("\033[1;31m[CHAT AUTH FAIL]\033[0m %s", auth_exc)
            raise
        history_uid = identity.session_uid
        staff_uid = identity.staff_uid
        logger.info(" Auth OK : session_uid=%s | staff_uid=%s", history_uid, staff_uid)

    # Pin the registered DB for ALL run_query calls in this request.
    # Analytics functions call run_query internally without _db_uid in their own params;
    # current_db_uid propagates to ThreadPoolExecutor workers (Python copies context on submit).
    _db_uid_token = current_db_uid.set(history_uid)
    logger.info(" DB routing : pinned to session_uid=%s", history_uid)

    question = (req.message or req.question or "").strip()
    # Phase 2 intentionally carries no message (it restores everything from the
    # job cache), so the empty-question guard must not fire for it.
    if not question and req.phase != 2:
        logger.warning("[CHAT] Empty question — returning early.")
        return {"answer": "I didn't catch that — could you please type your question?", "flag": None}

    try:
        staff_context = _get_staff_context(req, staff_uid)
        logger.info(" Staff context : %s", staff_context)
    except Exception as ctx_exc:
        logger.error("\033[1;31m[CHAT STAFF CONTEXT FAIL]\033[0m %s", ctx_exc, exc_info=True)
        staff_context = {"name": staff_uid, "designation": "Staff member"}

    # Per-UID output language & script preference
    try:
        output_lang = UserPrefsService.get_output_lang(staff_uid or req.userid)
    except Exception:
        output_lang = "auto"
    try:
        output_script = UserPrefsService.get_output_script(staff_uid or req.userid)
    except Exception:
        output_script = "native"
    if output_lang != "auto" or output_script != "native":
        logger.info(" Output pref : lang=%s | script=%s", output_lang, output_script)

    ai_analytics_enabled = _is_ai_analytics_enabled(request, req.ai_analytics)

    # ── Phase 2: LLM-answer-only path (restored from job cache) ──────
    if req.phase == 2:
        token = (req.job_token or req.job_id or "").strip()
        cached = _job_cache_get(token) if token else None
        if cached:
            _c_system = cached["system"]
            _c_user = cached["user"]
            _c_chart = cached.get("chart_spec")
            _c_rows = cached.get("rows") or []
            _c_cols = cached.get("columns") or []
            _c_flag = cached.get("flag")
            _c_desc = cached.get("flag_description")
            # Phase 2 has no message in the request body — restore it from cache.
            question = question or (cached.get("question") or "")
            _c_conv_id = cached.get("session_id", req.session_id or history_uid)
            _c_ai = cached.get("ai_analytics", True)
            _c_executed = cached.get("executed_data") or []
            _c_descriptions = cached.get("descriptions") or []
            _c_first_flag = cached.get("flag")
            _c_shape = cached.get("response_shape") or dict(_SHAPE_DEFAULT)

            # The branded briefing card is built HERE (Phase 2) so the report
            # follows the data snapshot and streams straight into the card.
            # 0-row queries skip the card and use the friendly empty state.
            # The response-shape engine selects the card variant (or no card).
            _c_has_data = any(
                not ds.get("error") and len(ds.get("rows") or ds.get("rows_full") or []) > 0
                for ds in (_c_executed or [])
            )
            try:
                _p2_briefing = build_phase1_briefing(
                    question, _c_descriptions, _c_executed, _c_first_flag,
                    shape=_c_shape.get("kind", "analytical"),
                ) if (_c_executed and _c_has_data) else {}
            except Exception as _be:
                logger.warning("[BRIEFING] phase2 build failed: %s", _be)
                _p2_briefing = {}
            _c_suggestions = cached.get("scope_suggestions") or []

            _snap_payload = {
                "chartSpec": _c_chart,
                "cols": _c_cols,
                "rows": _c_rows[:50],
                "snapshotText": _c_desc or "",
                "metricPills": [],
                "briefing": _p2_briefing or None,
            }

            if req.stream:
                if not _c_has_data:
                    # 0 rows: no LLM narrative — friendly empty state + suggestions.
                    def _phase2_empty_stream():
                        _friendly = "I couldn't find any data for that in your area or for the dates you mentioned." + _suggestions_block(_c_suggestions)
                        yield f"data: {json.dumps({'briefing': {}, 'done': False}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'delta': _friendly, 'done': False})}\n\n"
                        try:
                            save_turn(history_uid, _c_conv_id, question, _friendly, data_snapshot=_snap_payload)
                        except Exception as _hist_err:
                            logger.warning("[CHAT HISTORY FAIL] %s", _hist_err)
                        yield f"data: {json.dumps({'delta': '', 'done': True, 'full_answer': _friendly, 'briefing': {}, 'suggestions': _c_suggestions}, ensure_ascii=False)}\n\n"

                    current_db_uid.reset(_db_uid_token)
                    return StreamingResponse(
                        _phase2_empty_stream(),
                        media_type="text/event-stream; charset=utf-8",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "X-Accel-Buffering": "no",
                        },
                    )

                def _phase2_stream_generator():
                    full_chunks = []
                    # Ship the branded card first so it renders immediately and
                    # the analysis streams straight INTO it (no separate block).
                    try:
                        yield f"data: {json.dumps({'briefing': _p2_briefing, 'done': False}, ensure_ascii=False, default=str)}\n\n"
                    except Exception:
                        pass
                    try:
                        for delta in stream_oci_text(_c_system, _c_user):
                            if delta:
                                full_chunks.append(delta)
                                yield f"data: {json.dumps({'delta': delta, 'done': False})}\n\n"
                    except Exception as _stream_err:
                        logger.error("[STREAM ERROR] %s", _stream_err, exc_info=True)
                        err_delta = f"\n\n[Error generating analysis via OCI: {_stream_err}]"
                        full_chunks.append(err_delta)
                        yield f"data: {json.dumps({'delta': err_delta, 'done': False})}\n\n"

                    complete_answer = "".join(full_chunks)

                    try:
                        save_turn(history_uid, _c_conv_id, question, complete_answer, data_snapshot=_snap_payload)
                    except Exception as _hist_err:
                        logger.warning("[CHAT HISTORY FAIL] %s", _hist_err)

                    yield f"data: {json.dumps({'delta': '', 'done': True, 'full_answer': complete_answer, 'briefing': _p2_briefing, 'response_shape': _c_shape}, ensure_ascii=False, default=str)}\n\n"

                current_db_uid.reset(_db_uid_token)
                return StreamingResponse(
                    _phase2_stream_generator(),
                    media_type="text/event-stream; charset=utf-8",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )

            # Non-streaming Phase 2
            if not _c_has_data:
                # 0 rows: deterministic friendly message, no LLM call.
                phase2_answer = "I couldn't find any data for that in your area or for the dates you mentioned." + _suggestions_block(_c_suggestions)
            else:
                try:
                    phase2_answer = call_oci_text(_c_system, _c_user)
                except Exception as _oci_err:
                    logger.error("[OCI ERROR] %s", _oci_err, exc_info=True)
                    phase2_answer = f"Error generating analysis via OCI: {_oci_err}"

            try:
                save_turn(history_uid, _c_conv_id, question, phase2_answer, data_snapshot=_snap_payload)
            except Exception:
                pass

            p2_payload = {
                "phase": 2,
                "answer": phase2_answer,
                "job_token": token,
                "flag": _c_flag,
                "columns": _c_cols,
                "rows": _c_rows,
                "chart_spec": _c_chart,
                "briefing": _p2_briefing or None,
                "suggestions": _c_suggestions,
                "response_shape": _c_shape,
                "ai_analytics": _c_ai,
                "engine": "llm_analyst_phase2",
                "session_id": _c_conv_id,
            }
            current_db_uid.reset(_db_uid_token)
            return JSONResponse(content=json.loads(json.dumps(p2_payload, ensure_ascii=False, default=str)))
        else:
            logger.warning("[CHAT PHASE 2] Cache miss or expired token: %s", token)
            current_db_uid.reset(_db_uid_token)
            return JSONResponse(
                status_code=404,
                content={"error": "Job session expired. Please re-send your question."},
            )

    # ── Conversational & Greeting Fast-Path (<1ms, 0 Tokens, Direct BI Mode Only) ──
    if not ai_analytics_enabled:
        greeting_res = handle_general_or_greeting(question, staff_context)
        if greeting_res:
            greeting_res = _clean_markdown_formatting(greeting_res)
            logger.info("\033[1;32m[CHAT GREETING OK]\033[0m Handled via fast-path (<1ms, 0 LLM tokens)")
            logger.info("\033[1;36m%s\033[0m", SEP)
            current_db_uid.reset(_db_uid_token)
            return _with_history(request, req, {
                "answer": greeting_res,
                "flag": None,
                "rows": [],
                "columns": [],
                "chart_spec": None,
                "suggestions": [
                    "Show secondary sales for this month and top 5 distributors",
                    "Show primary sales trend for the last 6 months",
                    "Current closing stock by zone and depot",
                    "Total purchase value and distributor breakdown",
                ],
                "ai_analytics": False,
                "engine": "executive_bi_engine",
            })

    # ── Fast-Path In-Memory Cross-Questioning (Zero Data Exfiltration, <5ms) ──
    if not ai_analytics_enabled:
        session_conv_id = req.session_id or history_uid
        cq_answer = resolve_cross_questioning(
            staff_uid=staff_uid or history_uid,
            conversation_id=session_conv_id,
            question=question,
        )
        if cq_answer:
            cq_answer = _clean_markdown_formatting(cq_answer)
            logger.info("\033[1;32m[CHAT CROSS-QUESTIONING OK]\033[0m Resolved from in-memory session cache (<5ms, 0 LLM tokens)")
            logger.info("\033[1;36m%s\033[0m", SEP)
            current_db_uid.reset(_db_uid_token)
            return _with_history(request, req, {
                "answer": cq_answer,
                "flag": None,
                "rows": [],
                "columns": [],
                "chart_spec": None,
                "suggestions": [],
                "ai_analytics": False,
                "engine": "executive_bi_engine",
            })

    # Step 1: Route to analytics flag(s) via Gemini 3 Flash Preview (Rule 0 Natural Language Reasoning)
    logger.info("\033[1;33m[CHAT ROUTING]\033[0m Sending question to LLM router (Gemini 3 Flash Preview)...")
    try:
        routing = route_question(
            question,
            staff_uid,
            staff_context=staff_context,
            history=req.history,
            output_lang=output_lang,
            output_script=output_script,
        )
    except Exception as route_exc:
        logger.error("\033[1;31m[CHAT ROUTING FAIL]\033[0m %s", route_exc, exc_info=True)
        raise
    flags = routing.get("flags") or []
    params = routing.get("params") or {}
    direct_ans = routing.get("direct_answer") or ""
    shape = routing.get("response_shape") or dict(_SHAPE_DEFAULT)
    logger.info(" Routing result: flags=%s | params=%s | has_direct_answer=%s | shape=%s", flags, params, bool(direct_ans), shape.get("kind"))

    if direct_ans and not flags:
        # Step 1 Autonomous Natural Language Resolution (General greeting / identity / capabilities / domain inquiry)
        logger.info("\033[1;32m[CHAT STEP 1 DIRECT ANSWER]\033[0m Resolved autonomously via Step 1 Gemini intelligence (0 DB queries)")
        logger.info("\033[1;36m%s\033[0m", SEP)
        current_db_uid.reset(_db_uid_token)
        return _with_history(request, req, {
            "phase": 1,
            "job_token": None,
            "answer": direct_ans,
            "flag": None,
            "rows": [],
            "columns": [],
            "chart_spec": None,
            "suggestions": [
                "Show secondary sales for this month and top 5 distributors",
                "Show primary sales trend for the last 6 months",
                "Current closing stock by zone and depot",
                "Total purchase value and distributor breakdown",
            ],
            "response_shape": shape,
            "ai_analytics": ai_analytics_enabled,
            "engine": "llm_direct_step1",
        })

    if flags:
        # Step 2: Execute flag queries in parallel using ThreadPoolExecutor
        invalid = [f for f in flags if f not in ALL_FLAGS]
        valid_flags = [f for f in flags if f in ALL_FLAGS]
        if invalid:
            logger.warning("\033[1;33m[CHAT FLAGS]\033[0m Unknown flags (skipped): %s", invalid)
        if not valid_flags:
            logger.warning("\033[1;31m[CHAT FLAGS]\033[0m No valid flags found. Returning fallback answer.")
            suggs = get_scope_suggestions(staff_uid or "", history_uid)
            ans = "I wasn't able to find the right information for that. Could you try rephrasing your question?" + _suggestions_block(suggs)
            return _with_history(request, req, {"answer": ans, "flag": None, "rows": [], "columns": [], "suggestions": suggs, "ai_analytics": ai_analytics_enabled})
        logger.info("\033[1;32m[CHAT FLAGS]\033[0m Executing flags: %s | db_uid=%s | staff_uid=%s | params=%s",
            valid_flags, history_uid, staff_uid, params)

        def _exec_flag(flag_name: str):
            fn, desc = ALL_FLAGS[flag_name]
            flag_params = {**params, "_db_uid": history_uid}
            # Explicitly set current_db_uid AND allow_default_db inside THIS thread.
            # ThreadPoolExecutor does not reliably inherit ContextVars, so we set
            # them manually — otherwise the native chat's default-DB fallback is
            # denied inside flag workers.
            _thread_token = current_db_uid.set(history_uid)
            _allow_token = allow_default_db.set(_is_native_req)
            logger.info(" [FLAG START] %s | userid=%s | db_uid=%s | params=%s",
                flag_name, staff_uid, history_uid, flag_params)
            try:
                res = fn(staff_uid, flag_params)
                row_cnt = (res or {}).get("row_count", len((res or {}).get("rows", [])))
                err = (res or {}).get("error")
                if err:
                    logger.error(" [FLAG ERROR] %s returned error: %s", flag_name, err)
                else:
                    logger.info(" [FLAG OK] %s → %d rows | columns=%s",
                        flag_name, row_cnt, (res or {}).get("columns", []))
                return flag_name, desc, res, None
            except Exception as e:
                logger.error(" [FLAG EXCEPTION] %s | %s", flag_name, e, exc_info=True)
                _log_chat_exception("analytics flag execution failed", e, flag=flag_name, userid=staff_uid)
                return flag_name, desc, None, "data_unavailable"
            finally:
                allow_default_db.reset(_allow_token)
                current_db_uid.reset(_thread_token)

        results_by_flag = []
        with ThreadPoolExecutor(max_workers=min(8, len(valid_flags))) as pool:
            futures = [pool.submit(_exec_flag, f) for f in valid_flags]
            for fut in as_completed(futures):
                results_by_flag.append(fut.result())

        # Sort back to preserve intent order
        flag_order = {f: i for i, f in enumerate(valid_flags)}
        results_by_flag.sort(key=lambda x: flag_order.get(x[0], 0))

        descriptions = []
        all_rows = []
        all_columns = []
        total_row_count = 0
        errors = []
        first_exec = None
        first_flag = valid_flags[0]

        for flag_name, desc, execution, err in results_by_flag:
            descriptions.append((flag_name, desc))
            if err:
                errors.append(flag_name)
                continue
            if execution and execution.get("error"):
                if _chat_error_logs_enabled():
                    logger.error(
                        "[CHAT ERROR] analytics flag returned an error | flag=%s | userid=%s | error=%s",
                        flag_name, req.userid, execution["error"],
                    )
                errors.append(flag_name)
                continue

            if first_exec is None:
                first_exec = execution

            rows = (execution or {}).get("rows") or []
            for r in rows:
                r["_flag"] = flag_name
                r["_desc"] = desc
            all_rows.extend(rows)
            if not all_columns:
                all_columns = (execution or {}).get("columns") or []
            total_row_count += (execution or {}).get("row_count", len(rows))

        if errors and not all_rows:
            suggs = get_scope_suggestions(staff_uid or "", history_uid)
            ans = "I wasn't able to pull that information right now. Please try again in a moment." + _suggestions_block(suggs)
            return _with_history(request, req, {"answer": ans, "flag": first_flag, "rows": [], "columns": [], "suggestions": suggs, "ai_analytics": ai_analytics_enabled})

        # Step 3: Build merged execution result
        merged_exec = {
            "rows": all_rows,
            "columns": all_columns,
            "row_count": total_row_count,
            "flags": [f for f, _ in descriptions],
            "descriptions": descriptions,
        }

        logger.info("\033[1;33m[CHAT SUMMARY]\033[0m total_rows=%d | errors=%s | columns=%s",
            total_row_count, errors, all_columns)

        # Per-flag datasets WITH their flag name, so the metric guard can group
        # by module and never fuse unrelated scopes. Used by OFF, Phase 1 cache
        # and Phase 2 briefing.
        executed_data_list = []
        for _fname, _fdesc, _execution, _err in results_by_flag:
            if _err or not _execution or _execution.get("error"):
                continue
            _ds = dict(_execution)
            _ds["flag"] = _fname
            if not _ds.get("rows_full"):
                _ds["rows_full"] = _ds.get("rows") or []
            executed_data_list.append(_ds)

        # Step 4: Generate answer & chart based on ai_analytics toggle
        # Validate the router's shape against the REAL executed data (upgrade
        # to the safe full format on any mismatch), then audit-log the decision.
        shape = _validate_shape_against_data(shape, executed_data_list, valid_flags)
        _log_shape_decision(question, valid_flags, shape, staff_uid or history_uid)
        if shape.get("kind") != "analytical":
            logger.info("\033[1;35m[CHAT SHAPE]\033[0m %s%s", shape.get("kind"), " (upgraded)" if shape.get("upgraded") else "")

        scope_suggestions = []
        if total_row_count == 0 and valid_flags:
            logger.info("\033[1;33m[CHAT SUGGESTIONS]\033[0m 0 rows returned — generating scope suggestions for userid='%s'", staff_uid)
            scope_suggestions = get_scope_suggestions(staff_uid or "", history_uid)
        # Explore chips for data answers follow the answer's shape; for 0-row
        # answers the DB-probed scope suggestions lead the recovery.
        explore_suggs = (
            scope_suggestions
            if total_row_count == 0
            else _explore_suggestions(shape.get("kind", "analytical"), descriptions, scope_suggestions)
        )

        if ai_analytics_enabled and req.phase == 1:
            # Phase 1: Return data snapshot & chart immediately (<800ms) and cache for Phase 2 streaming
            chart_spec = build_deterministic_chart_spec(question, first_exec or merged_exec)
            sys_prompt, usr_prompt = build_answer_prompts(
                question,
                first_flag,
                merged_exec,
                staff_context=staff_context,
                history=req.history,
                multi_flags=[f for f, _ in descriptions],
                scope_suggestions=scope_suggestions,
                output_lang=output_lang,
                output_script=output_script,
                shape=shape,
            )
            _job_token = str(uuid.uuid4())
            _job_cache_put(_job_token, {
                "system": sys_prompt,
                "user": usr_prompt,
                "chart_spec": chart_spec,
                "rows": all_rows,
                "columns": all_columns,
                "flag": first_flag,
                "flag_description": descriptions[0][1] if descriptions else "",
                "session_id": req.session_id or history_uid,
                "ai_analytics": True,
                # Cached so Phase 2 can build the branded briefing card.
                "executed_data": executed_data_list,
                "descriptions": descriptions,
                "question": question,
                "scope_suggestions": explore_suggs,
                "response_shape": shape,
            })
            p1_payload = {
                "phase": 1,
                "job_token": _job_token,
                "answer": None,
                "flag": first_flag,
                "flag_description": descriptions[0][1] if descriptions else "",
                "columns": all_columns,
                "rows": all_rows,
                "row_count": total_row_count,
                "chart_spec": chart_spec,
                "briefing": None,  # report/briefing card is delivered in Phase 2
                "suggestions": explore_suggs,
                "response_shape": shape,
                "ai_analytics": True,
                "engine": "phase1_snapshot",
                "session_id": req.session_id or history_uid,
            }
            logger.info("\033[1;32m[CHAT PHASE 1 SNAPSHOT OK]\033[0m token=%s | rows=%d", _job_token, total_row_count)
            logger.info("\033[1;36m%s\033[0m", SEP)
            current_db_uid.reset(_db_uid_token)
            return JSONResponse(content=json.loads(json.dumps(p1_payload, ensure_ascii=False, default=str)))

        if ai_analytics_enabled:
            # Full AI Pipeline (Single-Turn Legacy) -- answer + chart spec run CONCURRENTLY
            # generate_answer and suggest_chart both read merged_exec as read-only; no race condition.
            import concurrent.futures as _cf

            _question    = question
            _first_flag  = first_flag
            _merged      = merged_exec
            _first_exec  = first_exec
            _multi_flags = [f for f, _ in descriptions]
            _staff_ctx   = staff_context
            _history     = req.history
            _suggs       = scope_suggestions
            _lang        = output_lang

            def _run_answer() -> str:
                logger.info("\033[1;33m[CHAT LLM ANSWER]\033[0m Calling generate_answer (parallel)...")
                return generate_answer(
                    _question,
                    _first_flag,
                    _merged,
                    multi_flags=_multi_flags,
                    staff_context=_staff_ctx,
                    history=_history,
                    scope_suggestions=_suggs,
                    output_lang=_lang,
                    shape=shape,
                )

            def _run_chart() -> dict:
                logger.info("\033[1;33m[CHAT CHART]\033[0m Calling suggest_chart (LLM, parallel)...")
                try:
                    return suggest_chart(_question, _first_exec or _merged)
                except Exception as _chart_exc:
                    logger.warning("[CHAT CHART FAIL] %s", _chart_exc)
                    return {}

            with _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="dms_llm") as _pool:
                _ans_future   = _pool.submit(_run_answer)
                _chart_future = _pool.submit(_run_chart)

                try:
                    answer = _ans_future.result(timeout=90)
                except Exception as ans_exc:
                    logger.error("\033[1;31m[CHAT ANSWER FAIL]\033[0m %s", ans_exc, exc_info=True)
                    # Graceful degradation instead of a 500 — the data is still shown.
                    answer = "I wasn't able to generate the narrative right now. Your data is shown above; please try again in a moment."

                try:
                    chart_spec = _chart_future.result(timeout=90)
                except Exception as _chart_exc:
                    logger.warning("[CHAT CHART FAIL] %s", _chart_exc)
                    chart_spec = {}

            # Post-process answer after both futures resolve
            if total_row_count == 0 and scope_suggestions:
                # 0 rows: replace the long narrative with a friendly empty-state
                # message + suggestions (chips also render up front).
                answer = "I couldn't find any data for that in your area or for the dates you mentioned." + _suggestions_block(scope_suggestions)
            elif total_row_count > 0 and explore_suggs:
                # Data answers always carry clickable "Try asking" chips.
                answer = answer + _suggestions_block(explore_suggs)
            answer = _clean_markdown_formatting(answer)
        else:
            # Deterministic High-End Executive BI Engine: Sub-100ms, Zero LLM tokens.
            # Concise synthesis (non-duplicative) + the branded report card payload.
            if total_row_count == 0 and valid_flags:
                # 0 rows: friendly empty-state instead of a full report card.
                logger.info("\033[1;33m[EXECUTIVE EMPTY]\033[0m 0 rows — friendly empty-state message")
                answer = "I couldn't find any data for that in your area or for the dates you mentioned." + _suggestions_block(scope_suggestions)
                answer = _clean_markdown_formatting(answer)
                briefing = {}
                chart_spec = {}
            else:
                logger.info("\033[1;35m[EXECUTIVE REPORT]\033[0m Generating deterministic BI report + briefing card...")
                try:
                    answer = generate_bi_analysis(
                        question,
                        merged_exec,
                        staff_context=staff_context,
                        first_flag=first_flag,
                        descriptions=descriptions,
                        output_lang=output_lang,
                        executed_data=executed_data_list,
                        conversation_id=req.session_id or history_uid,
                        staff_uid=staff_uid or history_uid,
                        history=req.history,
                    )
                except Exception as _bi_exc:
                    logger.error("\033[1;31m[EXECUTIVE FAIL]\033[0m %s", _bi_exc, exc_info=True)
                    answer = "I wasn't able to complete that analysis right now. Please try again in a moment."
                if explore_suggs:
                    # Data answers always carry clickable "Try asking" chips.
                    answer = answer + _suggestions_block(explore_suggs)
                answer = _clean_markdown_formatting(answer)
                try:
                    briefing = build_phase1_briefing(question, descriptions, executed_data_list, first_flag, shape=shape.get("kind", "analytical"))
                except Exception as _be:
                    logger.warning("[BRIEFING] build failed: %s", _be)
                    briefing = {}
                try:
                    chart_spec = build_deterministic_chart_spec(question, first_exec or merged_exec)
                except Exception as _cs_exc:
                    logger.warning("[CHART SPEC FAIL] %s", _cs_exc, exc_info=True)
                    chart_spec = {}
                logger.info("\033[1;35m[EXECUTIVE CHART]\033[0m Deterministic chart spec generated: %s",
                    chart_spec.get("chart_type") or "none"
                )

        payload = {
            "answer": answer,
            "flag": first_flag,
            "flag_description": descriptions[0][1] if descriptions else "",
            "columns": all_columns,
            "rows": all_rows,
            "row_count": total_row_count,
            "chart_spec": chart_spec,
            "briefing": briefing if not ai_analytics_enabled else None,
            "suggestions": explore_suggs,
            "response_shape": shape,
            "ai_analytics": ai_analytics_enabled,
            "engine": "llm_analyst" if ai_analytics_enabled else "executive_bi_engine",
        }
        logger.info("\033[1;32m[CHAT RESPONSE OK]\033[0m flag=%s | rows=%d | engine=%s | answer_len=%d chars",
            first_flag, total_row_count, payload["engine"], len(answer))
        logger.info("\033[1;36m%s\033[0m", SEP)
        current_db_uid.reset(_db_uid_token)
        return _with_history(request, req, payload)
    else:
        # General chat fallback
        logger.info("\033[1;33m[CHAT GENERAL]\033[0m No analytics flag matched. Using general answer fallback.")
        if ai_analytics_enabled:
            try:
                answer = generate_general_answer(question, req.history, staff_context=staff_context, output_lang=output_lang)
            except Exception as gen_exc:
                logger.error("\033[1;31m[CHAT GENERAL FAIL]\033[0m %s", gen_exc, exc_info=True)
                raise
        else:
            u_name = (staff_context or {}).get("name") or "there"
            answer = (
                f"DMS Direct Analytics Engine\n\n"
                f"Hello **{u_name}**! You are connected in Direct Analytics Mode (Instant BI Engine).\n\n"
                f"You can ask for instant executive reports on:\n"
                f"- Secondary Sales: \"Show top distributors by secondary sales this month\"\n"
                f"- Purchases: \"What were my total purchases this month?\"\n"
                f"- Primary Sales: \"Show primary sales trend for the last 6 months\"\n"
                f"- Stock Movement & Health: \"Show closing stock by zone\"\n"
                f"- Claims & Schemes: \"Show pending claims for my team\""
            )
            answer = _clean_markdown_formatting(answer)
        logger.info("\033[1;32m[CHAT RESPONSE OK]\033[0m general fallback | answer_len=%d chars", len(answer))
        logger.info("\033[1;36m%s\033[0m", SEP)
        current_db_uid.reset(_db_uid_token)
        return _with_history(request, req, {
            "answer": answer,
            "flag": None,
            "rows": [],
            "columns": [],
            "ai_analytics": ai_analytics_enabled,
            "engine": "llm_general" if ai_analytics_enabled else "instant_general",
        })


@router.get("/chat/history")
async def chat_history(
    request: Request,
    search: str = Query(default="", max_length=200),
    limit: int = Query(default=40, ge=1, le=100),
):
    """Return only the authenticated user's sessions, optionally searched."""
    return {"sessions": list_sessions(_history_uid(request), search=search, limit=limit)}
