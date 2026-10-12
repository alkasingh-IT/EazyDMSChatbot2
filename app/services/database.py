"""
DMS Database Service — per-UID session management for multi-tenant DB registration.

Supports:
  - Saving/loading per-user DB URLs (filesystem, keyed by uid)
  - AES-256-CBC decryption of registered DB URLs
  - RSA-OAEP decryption (alternate encryption path)
"""
import json
import logging
import os
import threading
import traceback
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("dms.database.service")

# ── In-memory session cache: { uid -> db_url } ─────────────────────────────
_session_lock = threading.Lock()
_sessions: dict = {}
_negative_cache: set = set()

_SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent / ".dms_sessions"


def _sess_file(uid: str) -> Path:
    try:
        uid = str(uuid.UUID(str(uid).strip()))
    except (ValueError, AttributeError):
        raise ValueError("Invalid session UUID")
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return _SESSIONS_DIR / f"{uid}.json"


def _mask_url(url: str) -> str:
    import re
    return re.sub(r':([^/@]+)@', r':****@', url)


def _get_aes_key() -> bytes:
    key_hex = (os.environ.get("DMS_AES_KEY_HEX") or "").strip()
    if not key_hex or len(key_hex) != 64:
        import hashlib
        return hashlib.sha256(b"dms_at_rest_default_session_key").digest()
    try:
        return bytes.fromhex(key_hex)
    except Exception:
        import hashlib
        return hashlib.sha256(b"dms_at_rest_default_session_key").digest()


def _encrypt_at_rest(plaintext: str) -> str:
    """Encrypt a string with AES-256-CBC -> iv_hex:cipher_hex."""
    key = _get_aes_key()
    iv = os.urandom(16)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    padder = sym_padding.PKCS7(128).padder()
    padded_data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    ct = encryptor.update(padded_data) + encryptor.finalize()
    return f"{iv.hex()}:{ct.hex()}"


def _decrypt_at_rest(token: str) -> str:
    """Decrypt iv_hex:cipher_hex string with AES-256-CBC."""
    if not token or ":" not in token:
        return token
    try:
        parts = token.split(":", 1)
        iv = bytes.fromhex(parts[0])
        ct = bytes.fromhex(parts[1])
        key = _get_aes_key()
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding as sym_padding
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded_plain = decryptor.update(ct) + decryptor.finalize()
        unpadder = sym_padding.PKCS7(128).unpadder()
        plain = unpadder.update(padded_plain) + unpadder.finalize()
        return plain.decode("utf-8")
    except Exception as e:
        logger.error("\033[1;31m[AT-REST DECRYPT FAIL]\033[0m Error: %s", e)
        return ""


def save_session_db_url(uid: str, db_url: str, staff_uid: str = "") -> bool:
    """Persist a DB URL for a given uid (memory + AES-256 encrypted disk file)."""
    try:
        with _session_lock:
            _sessions[uid] = db_url
            _negative_cache.discard(uid)
        p = _sess_file(uid)
        enc_url = _encrypt_at_rest(db_url)
        payload_data = json.dumps({
            "uid": str(uuid.UUID(str(uid).strip())),
            "staff_uid": str(staff_uid or "").strip(),
            "encrypted_db_url": enc_url,
        }, indent=2)
        p.write_text(payload_data, encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass

        logger.info(
            "\033[1;32m[SESSION STORED (ENCRYPTED AT REST)]\033[0m UID: \033[1;33m%s\033[0m | File: %s (%d bytes) | DB URL: \033[1;36m%s\033[0m",
            uid, p.name, len(payload_data), _mask_url(db_url)
        )
        return True
    except Exception as e:
        logger.error("\033[1;31m[SESSION STORE FAIL]\033[0m UID: %s | Error: %s", uid, e)
        return False


def get_session_db_url(uid: Optional[str] = None) -> Optional[str]:
    """
    Retrieve the registered DB URL strictly for a uid or active session context.
    NO FALLBACKS to arbitrary or other users' sessions.
    """
    keys_to_try = []
    if uid:
        keys_to_try.append(str(uid).strip())

    try:
        from ..db import current_user_id
        ctx_uid = current_user_id.get()
        if ctx_uid and str(ctx_uid).strip() and str(ctx_uid).strip() not in keys_to_try:
            keys_to_try.append(str(ctx_uid).strip())
    except Exception:
        pass

    if not keys_to_try:
        return None

    valid_keys = []
    for key in keys_to_try:
        try:
            valid_keys.append(str(uuid.UUID(key)))
        except (ValueError, AttributeError):
            continue
    keys_to_try = list(dict.fromkeys(valid_keys))
    if not keys_to_try:
        return None

    with _session_lock:
        # Fast path check
        for k in keys_to_try:
            if k in _sessions and _sessions[k]:
                return _sessions[k]
        
        # Check if all candidate keys are known negative misses
        if all(k in _negative_cache for k in keys_to_try):
            return None

    # Check disk for exact candidate keys ONLY
    for k in keys_to_try:
        p = _sess_file(k)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                enc_url = data.get("encrypted_db_url")
                if enc_url:
                    url = _decrypt_at_rest(enc_url)
                else:
                    url = data.get("db_url", "")
                if url:
                    with _session_lock:
                        _sessions[k] = url
                    return url
            except Exception as e:
                logger.error("\033[1;31m[SESSION DISK READ ERROR]\033[0m Key: %s | Error: %s", k, e)

    with _session_lock:
        for k in keys_to_try:
            _negative_cache.add(k)

    return None


def get_session_staff_uid(uid: str) -> Optional[str]:
    """Return the staff UID bound to a registered session UUID."""
    try:
        session_uid = str(uuid.UUID(str(uid).strip()))
    except (ValueError, AttributeError):
        return None
    try:
        p = _sess_file(session_uid)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        staff_uid = str(data.get("staff_uid") or "").strip()
        return staff_uid or None
    except Exception:
        return None


def has_session(uid: str) -> bool:
    return bool(get_session_db_url(uid))


def delete_session(uid: str) -> None:
    """Remove a session from memory and disk."""
    with _session_lock:
        _sessions.pop(uid, None)
        _negative_cache.discard(uid)
    p = _sess_file(uid)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
