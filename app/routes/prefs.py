"""
User Preference Routes — per-UID settings (output text language, etc.)

GET  /api/prefs/output-lang   → {ok, uid, lang, available_langs}
POST /api/prefs/output-lang   → {lang: "<code>"}  (422 on unknown code)

UID resolution order:
1. x-staff-uid / u-uid header
2. Connected staff UID bound to session UUID (x-uid) via get_session_staff_uid()
3. Explicit query param (?staff_uid= or ?uid=)
4. Request body payload (staff_uid or uid)
5. Fallback to session UUID (x-uid)
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from ..auth import _header
from ..services.database import get_session_staff_uid
from ..services.user_prefs import (
    UserPrefsService,
    VALID_OUTPUT_LANGS,
    OUTPUT_LANG_LABELS,
)

router = APIRouter(prefix="/api/prefs", tags=["prefs"])


def _resolve_pref_uid(
    req: Request,
    x_staff_uid: Optional[str] = None,
    x_uid: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    # 1. First priority: Authenticated identity verified by middleware
    identity = getattr(getattr(req, "state", None), "identity", None)
    if identity and getattr(identity, "staff_uid", None):
        return identity.staff_uid

    # 2. Direct staff UID from headers (x-staff-uid, u-uid, etc.)
    staff_uid = (
        (x_staff_uid or "").strip()
        or _header(req, "u-uid", "x-staff-uid", "x_staff_uid", "staff-uid", "staff_uid", "userid", "user-id", "user_id")
    )
    if staff_uid:
        return staff_uid

    # 3. Check session UUID (x-uid header or payload) and look up connected staff UID
    session_uid = (x_uid or "").strip() or _header(req, "x-uid", "x_uid")
    if not session_uid and payload:
        cand = str(payload.get("x_uid") or payload.get("session_uid") or "").strip()
        try:
            uuid.UUID(cand)
            session_uid = cand
        except (ValueError, AttributeError):
            pass

    if session_uid:
        connected_staff = get_session_staff_uid(session_uid)
        if connected_staff:
            return connected_staff

    return ""


@router.get("/output-lang")
async def get_output_lang(
    req: Request,
    uid: Optional[str] = None,
    x_staff_uid: Optional[str] = Header(None),
    x_uid: Optional[str] = Header(None),
) -> Dict[str, Any]:
    resolved = _resolve_pref_uid(req, x_staff_uid=x_staff_uid, x_uid=x_uid)
    if not resolved:
        raise HTTPException(status_code=401, detail="Valid registered session or staff UID required")
    return {
        "ok": True,
        "uid": resolved,
        "lang": UserPrefsService.get_output_lang(resolved),
        "available_langs": UserPrefsService.output_langs(),
    }


@router.post("/output-lang")
async def set_output_lang(req: Request) -> Dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    resolved = _resolve_pref_uid(req, payload=payload)
    if not resolved:
        raise HTTPException(status_code=401, detail="Valid registered session or staff UID required")

    lang = str((payload or {}).get("lang") or "").strip()
    if lang not in VALID_OUTPUT_LANGS:
        raise HTTPException(status_code=422, detail=f"Invalid lang. Valid: {sorted(VALID_OUTPUT_LANGS)}")

    saved = UserPrefsService.set_output_lang(resolved, lang)
    return {"ok": True, "uid": resolved, "lang": saved}
