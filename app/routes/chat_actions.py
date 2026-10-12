"""
DMS Chat Actions — response feedback (like/dislike) + quality reports.

Endpoints (all require a registered DMS session via require_request_identity):
  POST /api/chat/feedback   -> upsert/remove a rating for one turn
  GET  /api/chat/feedback   -> ratings map for one conversation
  POST /api/chat/report     -> file a quality/abuse report for one turn

Identity is ALWAYS resolved from the verified session/staff headers, never the
request body. Rate-limited per staff UID.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import require_request_identity
from ..services.chat_feedback import ChatFeedbackService, ChatReportService, REPORT_REASONS

router = APIRouter(prefix="/api", tags=["chat_actions"])

_RATE_GUARD = threading.Lock()
_RATE_WINDOWS: dict = {}
FEEDBACK_RATE = (60, 60)  # 60 feedback ops / 60s per staff UID


def _rate_limit(bucket: str, uid: str, max_n: int, window_s: int) -> None:
    key = f"{bucket}:{uid}"
    now = time.time()
    with _RATE_GUARD:
        dq = _RATE_WINDOWS.get(key)
        if dq is None:
            dq = deque()
            _RATE_WINDOWS[key] = dq
        while dq and now - dq[0] > window_s:
            dq.popleft()
        if len(dq) >= max_n:
            raise HTTPException(status_code=429, detail="Too many requests — please slow down.")
        dq.append(now)


class FeedbackRequest(BaseModel):
    conversation_id: str = Field(max_length=128, default="")
    turn_index: int = Field(ge=0, le=10_000, default=0)
    rating: Optional[str] = Field(default=None, pattern="^(like|dislike)$")
    question: str = Field(max_length=5000, default="")
    answer: str = Field(max_length=100_000, default="")


class ReportRequest(BaseModel):
    conversation_id: str = Field(max_length=128, default="")
    turn_index: int = Field(ge=0, le=10_000, default=0)
    reason: str = Field(pattern="^(inaccurate_data|misleading_analysis|irrelevant_answer|confusing_formatting|offensive_content|permission_issue|other)$")
    details: str = Field(max_length=500, default="")
    question: str = Field(max_length=5000, default="")
    answer: str = Field(max_length=100_000, default="")


@router.post("/chat/feedback")
async def save_feedback(body: FeedbackRequest, request: Request):
    identity = require_request_identity(request)
    uid = identity.staff_uid
    _rate_limit("fb", uid, *FEEDBACK_RATE)
    if not (body.conversation_id or "").strip():
        raise HTTPException(status_code=400, detail="conversation_id is required")

    if body.rating is None:
        ok = ChatFeedbackService.remove_rating(uid, body.conversation_id, body.turn_index)
    else:
        ok = ChatFeedbackService.save_feedback(
            uid=uid, conversation_id=body.conversation_id, turn_index=body.turn_index,
            rating=body.rating, question=body.question, answer=body.answer,
        )
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to record feedback")
    summary = ChatFeedbackService.get_conversation_feedback(uid, body.conversation_id)
    return {"ok": True, **summary}


@router.get("/chat/feedback")
async def get_feedback(request: Request, conversation_id: str = ""):
    identity = require_request_identity(request)
    uid = identity.staff_uid
    if not (conversation_id or "").strip():
        raise HTTPException(status_code=400, detail="conversation_id is required")
    return {"ok": True, **ChatFeedbackService.get_conversation_feedback(uid, conversation_id)}


@router.post("/chat/report")
async def file_report(body: ReportRequest, request: Request):
    identity = require_request_identity(request)
    uid = identity.staff_uid
    _rate_limit("report", uid, *FEEDBACK_RATE)
    if not (body.conversation_id or "").strip():
        raise HTTPException(status_code=400, detail="conversation_id is required")

    ok = ChatReportService.file_report(
        uid=uid, conversation_id=body.conversation_id, turn_index=body.turn_index,
        reason=body.reason, details=body.details,
        question=body.question, answer=body.answer,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid report — check reason/details")
    reasons = ChatReportService.get_turn_reports(uid, body.conversation_id, body.turn_index)
    return {"ok": True, "turn_reasons": reasons}
