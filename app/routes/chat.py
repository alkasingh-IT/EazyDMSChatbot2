import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..db import run_query, current_db_uid
from ..analytics import ALL_FLAGS
from ..services.chat import (
    generate_answer,
    generate_general_answer,
    get_scope_suggestions,
    route_question,
    suggest_chart,
)
from ..services.executive_report import (
    generate_executive_report,
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
    message: str = Field(..., max_length=4096)
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


def _history_uid(request: Request) -> str:
    return require_request_identity(request).session_uid


def _with_history(request: Request, req: ChatRequest, payload: Dict[str, Any]) -> Dict[str, Any]:
    uid = _history_uid(request)
    session_id = req.session_id or str(uuid.uuid4())
    try:
        save_turn(uid, session_id, req.message, payload.get("answer", ""))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Chat history write failed for session UUID %s", uid)
        raise HTTPException(status_code=503, detail="Chat response could not be stored safely") from exc
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

    question = (req.message or "").strip()
    if not question:
        logger.warning("[CHAT] Empty question — returning early.")
        return {"answer": "I didn't catch that — could you please type your question?", "flag": None}

    try:
        staff_context = _get_staff_context(req, staff_uid)
        logger.info(" Staff context : %s", staff_context)
    except Exception as ctx_exc:
        logger.error("\033[1;31m[CHAT STAFF CONTEXT FAIL]\033[0m %s", ctx_exc, exc_info=True)
        staff_context = {"name": staff_uid, "designation": "Staff member"}

    # Per-UID output language preference (auto = mirror the question's language)
    try:
        output_lang = UserPrefsService.get_output_lang(staff_uid or req.userid)
    except Exception:
        output_lang = "auto"
    if output_lang != "auto":
        logger.info(" Output lang : %s", output_lang)

    ai_analytics_enabled = _is_ai_analytics_enabled(request, req.ai_analytics)

    # ── Conversational & Greeting Fast-Path (<1ms, 0 Tokens) ──
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
            "ai_analytics": ai_analytics_enabled,
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

    # Step 1: Route to analytics flag(s)
    logger.info("\033[1;33m[CHAT ROUTING]\033[0m Sending question to LLM router...")
    try:
        routing = route_question(question, staff_uid, staff_context=staff_context, history=req.history)
    except Exception as route_exc:
        logger.error("\033[1;31m[CHAT ROUTING FAIL]\033[0m %s", route_exc, exc_info=True)
        raise
    flags = routing.get("flags") or []
    params = routing.get("params") or {}
    logger.info(" Routing result: flags=%s | params=%s", flags, params)

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
            # Explicitly set current_db_uid inside THIS thread.
            # ThreadPoolExecutor only auto-copies ContextVars in Python 3.12+;
            # on older versions we must set it manually so analytics functions'
            # internal run_query calls route to the registered DB, not DATABASE_URL.
            _thread_token = current_db_uid.set(history_uid)
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

        # Step 4: Generate answer & chart based on ai_analytics toggle
        scope_suggestions = []
        if total_row_count == 0 and valid_flags:
            logger.info("\033[1;33m[CHAT SUGGESTIONS]\033[0m 0 rows returned — generating scope suggestions for userid='%s'", staff_uid)
            scope_suggestions = get_scope_suggestions(staff_uid or "", history_uid)

        if ai_analytics_enabled:
            # Full AI Pipeline: LLM Business Analyst + LLM Chart Suggestion
            logger.info("\033[1;33m[CHAT LLM ANSWER]\033[0m Calling generate_answer...")
            try:
                answer = generate_answer(
                    question,
                    first_flag,
                    merged_exec,
                    multi_flags=[f for f, _ in descriptions],
                    staff_context=staff_context,
                    history=req.history,
                    scope_suggestions=scope_suggestions,
                    output_lang=output_lang,
                )
            except Exception as ans_exc:
                logger.error("\033[1;31m[CHAT ANSWER FAIL]\033[0m %s", ans_exc, exc_info=True)
                raise

            # Guarantee suggestions appear even if the LLM omitted them
            if total_row_count == 0 and scope_suggestions:
                answer = answer.rstrip() + _suggestions_block(scope_suggestions)
            answer = _clean_markdown_formatting(answer)

            # Step 5: Suggest chart from first non-empty execution
            logger.info("\033[1;33m[CHAT CHART]\033[0m Calling suggest_chart (LLM)...")
            try:
                chart_spec = suggest_chart(question, first_exec or merged_exec)
            except Exception as chart_exc:
                logger.warning("[CHAT CHART FAIL] %s", chart_exc)
                chart_spec = {}
        else:
            # Deterministic High-End Executive BI Engine: Sub-100ms, Zero LLM tokens
            logger.info("\033[1;35m[EXECUTIVE REPORT]\033[0m Generating deterministic high-end BI briefing...")
            executed_data_list = [res[2] for res in results_by_flag if len(res) > 2 and res[2]]
            answer = generate_executive_report(
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
            answer = _clean_markdown_formatting(answer)
            chart_spec = build_deterministic_chart_spec(question, first_exec or merged_exec)
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
            "suggestions": scope_suggestions,
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
