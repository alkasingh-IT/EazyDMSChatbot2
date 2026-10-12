"""Request authentication helpers for the server-issued DMS session UUID."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class RequestIdentity:
    session_uid: str
    staff_uid: str


def _header(request: Request, *names: str) -> str:
    for name in names:
        value = (request.headers.get(name) or "").strip()
        if value:
            return value
    return ""


def require_request_identity(request: Request, allow_session_staff_resolution: bool = False) -> RequestIdentity:
    session_uid = _header(request, "x-uid", "x_uid")
    # Staff UID — "u-uid" is accepted as a full alternative to "x-staff-uid"
    staff_uid = _header(request, "u-uid", "x-staff-uid", "x_staff_uid")
    if not session_uid:
        raise HTTPException(status_code=401, detail="X-UID is required")
    try:
        session_uid = str(uuid.UUID(session_uid))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="X-UID must be a valid session UUID")
    from .services.database import get_session_db_url, get_session_staff_uid
    if not get_session_db_url(session_uid):
        raise HTTPException(status_code=401, detail="X-UID is not a registered session")
    registered_staff_uid = get_session_staff_uid(session_uid)

    # If enabled for specific APIs (like prefs), allow resolving staff_uid from the verified session
    if allow_session_staff_resolution and not staff_uid and registered_staff_uid:
        staff_uid = registered_staff_uid

    if not staff_uid:
        raise HTTPException(status_code=401, detail="X-UID and X-Staff-UID are required")
    if len(staff_uid) > 256:
        raise HTTPException(status_code=401, detail="Invalid X-Staff-UID")
    if registered_staff_uid and registered_staff_uid != staff_uid:
        raise HTTPException(status_code=401, detail="X-UID is not registered for this X-Staff-UID")
    return RequestIdentity(session_uid=session_uid, staff_uid=staff_uid)


def is_public_path(path: str) -> bool:
    return path in {
        "/",
        "/health",
        "/api/db/register",
        "/api/crypto/public-key",
    } or path.startswith("/static") or path.startswith("/chat")

