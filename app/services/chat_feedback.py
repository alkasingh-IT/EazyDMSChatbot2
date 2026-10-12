"""
DMS Chat Feedback Service
Records like/dislike ratings and quality reports for assistant responses,
indexed by the authenticated staff UID (from the request identity — never the
body).

Storage: one JSON file per staff UID under
{BASE_DIR}/metadata_reports/chat_feedback/{uid}.json (and .../chat_reports/...).
One rating per (conversation_id, turn_index) — upsert semantics.

Hardening:
- per-UID threading locks (no concurrent-write corruption)
- strict field validation with hard length caps
- uid always from auth identity, never from the request body
- preview-only persistence of question/answer snippets
- atomic write
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..config.settings import settings

_MAX_RECORDS_PER_UID = 2000
_LOCKS_GUARD = threading.Lock()
_UID_LOCKS: Dict[str, threading.Lock] = {}

VALID_RATINGS = ("like", "dislike")

REPORT_REASONS = (
    "inaccurate_data",
    "misleading_analysis",
    "irrelevant_answer",
    "confusing_formatting",
    "offensive_content",
    "permission_issue",
    "other",
)
_VALID_REASONS = set(REPORT_REASONS)


def _base_dir() -> Path:
    return Path(getattr(settings, "BASE_DIR", ".")) / "metadata_reports"


def _uid_lock(uid: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _UID_LOCKS.get(uid)
        if lock is None:
            lock = threading.Lock()
            _UID_LOCKS[uid] = lock
        return lock


def _sanitize_cid(conversation_id: str) -> str:
    return "".join(c for c in str(conversation_id or "").strip()[:128] if c.isalnum() or c in "-_")


class ChatFeedbackService:
    """Like/dislike feedback records keyed by staff UID."""

    @staticmethod
    def _path(uid: str) -> Path:
        return _base_dir() / "chat_feedback" / f"{uid}.json"

    @staticmethod
    def _load(uid: str) -> Dict[str, Any]:
        p = ChatFeedbackService._path(uid)
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("records"), list):
                    return data
        except Exception:
            pass
        return {"records": [], "updated_at": None}

    @staticmethod
    def _save(uid: str, data: Dict[str, Any]) -> None:
        p = ChatFeedbackService._path(uid)
        os.makedirs(str(p.parent), exist_ok=True)
        data["updated_at"] = datetime.utcnow().isoformat() + "Z"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(str(tmp), str(p))

    @staticmethod
    def save_feedback(uid: str, conversation_id: str, turn_index: int, rating: str,
                      question: str = "", answer: str = "") -> bool:
        uid = str(uid or "").strip()[:128]
        cid = _sanitize_cid(conversation_id)
        if not uid or not cid or rating not in VALID_RATINGS:
            return False
        try:
            turn_index = max(0, min(int(turn_index), 10_000))
        except (TypeError, ValueError):
            return False
        now = datetime.utcnow().isoformat() + "Z"
        record = {
            "conversation_id": cid, "turn_index": turn_index, "rating": rating,
            "question_preview": str(question or "").strip()[:200],
            "answer_preview": str(answer or "").strip()[:500],
            "created_at": now, "updated_at": now,
        }
        with _uid_lock(uid):
            try:
                data = ChatFeedbackService._load(uid)
                records = data.get("records", [])
                replaced = False
                for i, r in enumerate(records):
                    if r.get("conversation_id") == cid and r.get("turn_index") == turn_index:
                        records[i] = record
                        replaced = True
                        break
                if not replaced:
                    records.append(record)
                data["records"] = records[-_MAX_RECORDS_PER_UID:]
                ChatFeedbackService._save(uid, data)
            except Exception as e:
                print(f"[feedback] Save failed uid={uid[:8]}...: {e}")
                return False
        return True

    @staticmethod
    def remove_rating(uid: str, conversation_id: str, turn_index: int) -> bool:
        uid = str(uid or "").strip()[:128]
        cid = _sanitize_cid(conversation_id)
        if not uid or not cid:
            return False
        try:
            turn_index = max(0, min(int(turn_index), 10_000))
        except (TypeError, ValueError):
            return False
        with _uid_lock(uid):
            try:
                data = ChatFeedbackService._load(uid)
                original = len(data.get("records", []))
                data["records"] = [
                    r for r in data.get("records", [])
                    if not (r.get("conversation_id") == cid and r.get("turn_index") == turn_index)
                ]
                if len(data["records"]) == original:
                    return True
                ChatFeedbackService._save(uid, data)
            except Exception as e:
                print(f"[feedback] Remove failed uid={uid[:8]}...: {e}")
                return False
        return True

    @staticmethod
    def get_conversation_feedback(uid: str, conversation_id: str) -> Dict[str, Any]:
        uid = str(uid or "").strip()[:128]
        cid = _sanitize_cid(conversation_id)
        if not uid or not cid:
            return {"turns": {}, "likes": 0, "dislikes": 0, "mine": {}}
        try:
            data = ChatFeedbackService._load(uid)
            mine: Dict[str, str] = {}
            likes = dislikes = 0
            for r in data.get("records", []):
                if r.get("conversation_id") != cid:
                    continue
                mine[str(r.get("turn_index"))] = r.get("rating")
                if r.get("rating") == "like":
                    likes += 1
                elif r.get("rating") == "dislike":
                    dislikes += 1
            return {"turns": mine, "likes": likes, "dislikes": dislikes, "mine": mine}
        except Exception:
            return {"turns": {}, "likes": 0, "dislikes": 0, "mine": {}}


class ChatReportService:
    """Quality/abuse reports for assistant responses, keyed by staff UID."""

    @staticmethod
    def _path(uid: str) -> Path:
        return _base_dir() / "chat_reports" / f"{uid}.json"

    @staticmethod
    def _load(uid: str) -> Dict[str, Any]:
        p = ChatReportService._path(uid)
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("reports"), list):
                    return data
        except Exception:
            pass
        return {"reports": [], "updated_at": None}

    @staticmethod
    def _save(uid: str, data: Dict[str, Any]) -> None:
        p = ChatReportService._path(uid)
        os.makedirs(str(p.parent), exist_ok=True)
        data["updated_at"] = datetime.utcnow().isoformat() + "Z"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(str(tmp), str(p))

    @staticmethod
    def file_report(uid: str, conversation_id: str, turn_index: int, reason: str,
                    details: str = "", question: str = "", answer: str = "") -> bool:
        uid = str(uid or "").strip()[:128]
        cid = _sanitize_cid(conversation_id)
        if not uid or not cid or reason not in _VALID_REASONS:
            return False
        try:
            turn_index = max(0, min(int(turn_index), 10_000))
        except (TypeError, ValueError):
            return False
        details = " ".join(str(details or "").split())[:500]
        if reason == "other" and not details:
            return False
        now = datetime.utcnow().isoformat() + "Z"
        report = {
            "report_id": f"{cid[:12]}_{turn_index}_{int(datetime.utcnow().timestamp()*1000)}",
            "conversation_id": cid, "turn_index": turn_index, "reason": reason,
            "details": details,
            "question_preview": str(question or "").strip()[:200],
            "answer_preview": str(answer or "").strip()[:500],
            "status": "open", "created_at": now,
        }
        with _uid_lock(uid):
            try:
                data = ChatReportService._load(uid)
                reports = data.get("reports", [])
                for r in reports:
                    if (r.get("conversation_id") == cid and r.get("turn_index") == turn_index
                            and r.get("reason") == reason):
                        return True
                reports.append(report)
                data["reports"] = reports[-_MAX_RECORDS_PER_UID:]
                ChatReportService._save(uid, data)
            except Exception as e:
                print(f"[report] Save failed uid={uid[:8]}...: {e}")
                return False
        return True

    @staticmethod
    def get_turn_reports(uid: str, conversation_id: str, turn_index: int) -> List[str]:
        uid = str(uid or "").strip()[:128]
        cid = _sanitize_cid(conversation_id)
        try:
            data = ChatReportService._load(uid)
            return [r["reason"] for r in data.get("reports", [])
                    if r.get("conversation_id") == cid and r.get("turn_index") == turn_index]
        except Exception:
            return []
