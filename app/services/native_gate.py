"""
DMS Native Chat Access Gate (d3 test harness)
=============================================
Backend-only password protection for the DMS d3 chat component
(/d3/DMSAIChat.jsx) and its test harness page (/dmsai).

Access uses standard HTTP Basic Auth, so the BROWSER renders the password
prompt — no frontend code is involved. The server stores only a salted SHA-256
hash and compares in constant time.

Configuration (env):
  NATIVE_CHAT_ENABLED=1|0              master toggle (OFF → /d3 + /dmsai 404)
  NATIVE_CHAT_ACCESS_USER             basic-auth username (default "owzy")
  NATIVE_CHAT_ACCESS_PASSWORD         access password (plaintext env)
  NATIVE_CHAT_ACCESS_PASSWORD_HASH    preferred: "sha256$<salt_hex>$<hash_hex>"
If neither password var is set, a strong password is generated on first boot,
printed ONCE to the console, and only its hash persisted in
app/services/native_chat_access.json (reset by deleting that file).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

try:
    from ..config.settings import settings
except ImportError:
    from config.settings import settings

_GATE_DIR = Path(__file__).parent
_STATE_FILE = _GATE_DIR / "native_chat_access.json"
_LOCK = threading.Lock()

REALM = "Owzy Native Chat"


def make_password_hash(password: str, salt_hex: Optional[str] = None) -> str:
    salt = salt_hex or secrets.token_hex(16)
    h = hashlib.sha256((salt + str(password)).encode("utf-8")).hexdigest()
    return f"sha256${salt}${h}"


def _parse_hash(spec: str):
    try:
        algo, salt, h = str(spec).split("$", 2)
        if algo == "sha256" and salt and h:
            return salt, h
    except Exception:
        pass
    return None, None


def _load_state() -> dict:
    try:
        if _STATE_FILE.exists():
            d = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _save_state(d: dict) -> None:
    tmp = _STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(_STATE_FILE))


def _configured_hash() -> str:
    spec = (os.environ.get("NATIVE_CHAT_ACCESS_PASSWORD_HASH") or "").strip()
    if spec and _parse_hash(spec)[0]:
        return spec

    plain = (os.environ.get("NATIVE_CHAT_ACCESS_PASSWORD") or "").strip()
    if plain:
        return make_password_hash(plain)

    with _LOCK:
        st = _load_state()
        if st.get("password_hash") and _parse_hash(st["password_hash"])[0]:
            return st["password_hash"]
        pw = secrets.token_urlsafe(18)
        spec = make_password_hash(pw)
        st["password_hash"] = spec
        _save_state(st)
        print(
            "\n" + "=" * 70 +
            "\n[DMS Native Chat] ACCESS PASSWORD (generated once — store it safely):\n"
            f"    username: {basic_username()}\n"
            f"    password: {pw}\n" +
            "=" * 70, flush=True,
        )
        return spec


def basic_username() -> str:
    return (os.environ.get("NATIVE_CHAT_ACCESS_USER") or "owzy").strip()


def verify_password(password: str) -> bool:
    salt, expected = _parse_hash(_configured_hash())
    if not salt or not expected:
        return False
    got = hashlib.sha256((salt + str(password or "")).encode("utf-8")).hexdigest()
    return hmac.compare_digest(got, expected)


def check_basic_auth(request) -> bool:
    raw = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not raw.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(raw.split(" ", 1)[1].strip()).decode("utf-8", "replace")
        user, _, pw = decoded.partition(":")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    if not hmac.compare_digest(user, basic_username()):
        return False
    return verify_password(pw)


def challenge_headers() -> dict:
    return {"WWW-Authenticate": f'Basic realm="{REALM}"'}


def enabled() -> bool:
    return bool(getattr(settings, "NATIVE_CHAT_ENABLED", True))


# ── Signed gate cookie ───────────────────────────────────────────────────────
# The browser does NOT send Basic credentials on JS fetch() calls to /api/*, so
# after a successful password unlock on /d3 we also set a signed cookie that the
# browser then sends automatically to every same-origin request.
_COOKIE_NAME = "nc_gate"
_COOKIE_TTL = 12 * 3600


def _secret() -> bytes:
    base = (
        os.environ.get("NATIVE_CHAT_TOKEN_SECRET")
        or getattr(settings, "DMS_AES_KEY_HEX", "")
        or os.environ.get("DB_AES_KEY_HEX")
        or "dms-native-gate-default"
    )
    return hashlib.sha256(("nc-gate::" + str(base)).encode()).digest()


def issue_cookie() -> str:
    exp = int(time.time()) + _COOKIE_TTL
    payload = f"ncg.1.{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_cookie(request) -> bool:
    try:
        raw = request.cookies.get(_COOKIE_NAME) or ""
    except Exception:
        return False
    if not raw.startswith("ncg.1."):
        return False
    try:
        payload, sig = raw.rsplit(".", 1)
        exp = int(payload.split(".")[2])
    except Exception:
        return False
    if exp < time.time():
        return False
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def is_native_chat(request) -> bool:
    """
    True for the embedded native chat — detected ENTIRELY on the backend:
    master toggle ON and (valid Basic credentials OR a valid gate cookie).

    Basic is what the /d3 password prompt provides; the signed cookie is set on
    that successful unlock so it is also sent on JS fetch() calls to /api/*.
    This is the ONLY source allowed to use the default DATABASE_URL.
    """
    if not enabled():
        return False
    return check_basic_auth(request) or verify_cookie(request)
