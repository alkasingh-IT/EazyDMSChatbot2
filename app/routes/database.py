"""
DMS Database Registration Routes

Implements the SFA integration pattern for DMS:

  POST /api/db/register          — register encrypted DB URL (AES-256 or RSA)
  GET  /api/crypto/public-key    — fetch RSA public key for client-side encryption
"""
import logging
import os
import re
import threading
import traceback
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..services.database import save_session_db_url, get_session_db_url
from ..auth import _header

router = APIRouter(prefix="/api", tags=["database"])
logger = logging.getLogger("dms.database")

# ── RSA key management ───────────────────────────────────────────────────────
_rsa_private_key = None
_rsa_lock = threading.Lock()
_RSA_KEY_FILE = Path(__file__).resolve().parent.parent.parent / ".dms_rsa_private_key.pem"


def _mask_url(url: str) -> str:
    return re.sub(r':([^/@]+)@', r':****@', url)


def _get_rsa_private_key():
    global _rsa_private_key
    with _rsa_lock:
        if _rsa_private_key is not None:
            return _rsa_private_key
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        passphrase = (os.environ.get("DMS_RSA_PASSPHRASE") or "").encode("utf-8") or None

        pem_env = (os.environ.get("DMS_RSA_PRIVATE_KEY_PEM") or "").strip()
        if pem_env:
            _rsa_private_key = load_pem_private_key(pem_env.encode(), password=passphrase)
            logger.info("\033[1;34m[RSA KEY]\033[0m Loaded RSA private key from environment variable")
            return _rsa_private_key
        if _RSA_KEY_FILE.exists():
            _rsa_private_key = load_pem_private_key(_RSA_KEY_FILE.read_bytes(), password=passphrase)
            logger.info("\033[1;34m[RSA KEY]\033[0m Loaded RSA private key from secure file")
            return _rsa_private_key
        
        # Generate + persist a new protected RSA key
        _rsa_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        try:
            encryption_algo = (
                serialization.BestAvailableEncryption(passphrase)
                if passphrase
                else serialization.NoEncryption()
            )
            key_bytes = _rsa_private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                encryption_algo,
            )
            _RSA_KEY_FILE.write_bytes(key_bytes)
            try:
                os.chmod(_RSA_KEY_FILE, 0o600)
            except Exception:
                pass
            logger.info("\033[1;32m[RSA KEY CREATED]\033[0m Generated new protected RSA key pair to: %s", _RSA_KEY_FILE)
        except Exception as e:
            logger.warning("\033[1;33m[RSA KEY SAVE WARN]\033[0m Could not save RSA key to disk: %s", e)
        return _rsa_private_key


# ── Models ───────────────────────────────────────────────────────────────────

class RegisterDatabaseRequest(BaseModel):
    encrypted_db_url_b64: Optional[str] = None
    encrypted_db_url: Optional[str] = None
    db_url: Optional[str] = None
    token: Optional[str] = None
    encrypted_token: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _looks_like_hex(s: str) -> bool:
    try:
        bytes.fromhex(s)
        return True
    except Exception:
        return False


def _get_aes_key() -> bytes:
    key_hex = (os.environ.get("DMS_AES_KEY_HEX") or "").strip()
    if not key_hex or len(key_hex) != 64 or not _looks_like_hex(key_hex):
        import hashlib
        return hashlib.sha256(b"dms_at_rest_default_session_key").digest()
    return bytes.fromhex(key_hex)


def _decrypt_aes_hex_iv_cipher(token: str) -> str:
    """Decrypt iv_hex:cipher_hex token with AES-256-CBC (PKCS7 padding)."""
    parts = token.split(":", 1)
    if len(parts) != 2:
        raise ValueError("Invalid token format — expected iv_hex:cipher_hex")
    iv_hex, cipher_hex = parts[0].strip(), parts[1].strip()
    if len(iv_hex) != 32 or not _looks_like_hex(iv_hex) or not _looks_like_hex(cipher_hex):
        raise ValueError("Invalid hex values in token")

    key = _get_aes_key()

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    iv = bytes.fromhex(iv_hex)
    ciphertext = bytes.fromhex(cipher_hex)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded_plain = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded_plain) + unpadder.finalize()
    return plain.decode("utf-8").strip()


def _decrypt_rsa_b64(token: str) -> str:
    """Decrypt RSA-OAEP encrypted, base64-encoded ciphertext."""
    import base64
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import hashes

    ciphertext = base64.b64decode(token)
    plaintext = _get_rsa_private_key().decrypt(
        ciphertext,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return plaintext.decode("utf-8").strip()


def is_debug() -> bool:
    return os.environ.get("DEBUG_LOGS", "false").lower() in ("true", "1", "yes", "debug")


def is_detailed_error_logging_enabled() -> bool:
    val = os.environ.get("DETAILED_ERROR_LOGS", os.environ.get("DEBUG_LOGS", "true")).lower()
    return val in ("true", "1", "yes", "on", "debug")


def debug_print(*args, **kwargs):
    if is_debug():
        masked_args = []
        for arg in args:
            if isinstance(arg, str) and "://" in arg:
                arg = re.sub(r':([^/@]+)@', r':****@', arg)
            masked_args.append(arg)
        print(*masked_args, **kwargs)


def log_detailed_error(context_tag: str, error: Exception, extra_info: dict = None):
    """
    Log highly detailed diagnostic error details when DETAILED_ERROR_LOGS=true.
    Can be turned off via environment variable: DETAILED_ERROR_LOGS=false
    """
    logger.error("\033[1;31m[%s FAIL]\033[0m %s", context_tag, error)
    if is_detailed_error_logging_enabled():
        lines = [
            f"\n\033[1;31m{'='*25} [DETAILED ERROR DIAGNOSTIC: {context_tag}] {'='*25}\033[0m",
            f"Error Type    : {type(error).__name__}",
            f"Error Details : {error}",
        ]
        if extra_info:
            lines.append("Context Metadata:")
            for k, v in extra_info.items():
                v_str = str(v)
                if "://" in v_str:
                    v_str = _mask_url(v_str)
                lines.append(f"  - {k}: {v_str}")
        lines.append("Full Traceback:")
        tb_str = traceback.format_exc().strip()
        lines.append(tb_str if tb_str != "NoneType: None" else "  (No exception traceback available)")
        lines.append("\033[1;33m[TIP] To disable these verbose error logs, set DETAILED_ERROR_LOGS=false in .env\033[0m")
        lines.append(f"\033[1;31m{'='*80}\033[0m\n")
        logger.error("\n".join(lines))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/db/register")
async def register_db(request: Request):
    """
    Step 1 — Register an encrypted database URL.
    Supports AES-256-CBC, RSA-OAEP, or direct SQLAlchemy URL.
    """
    logger.info("\033[1;36m[DMS DB REGISTER START]\033[0m Endpoint invoked")
    debug_print("\n" + "=" * 80)
    debug_print("[DMS DB REGISTER] Endpoint Called - Debug Trace Enabled")
    debug_print(f"[DMS DB REGISTER] Request Headers: {dict(request.headers)}")

    try:
        payload = await request.json()
        debug_print(f"[DMS DB REGISTER] Raw Request Body: {payload}")
    except Exception as parse_err:
        log_detailed_error("DMS DB REGISTER JSON PARSE", parse_err, {"headers": dict(request.headers)})
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    token = ""
    if isinstance(payload, dict):
        token = (
            payload.get("encrypted_db_url_b64")
            or payload.get("encrypted_db_url")
            or payload.get("db_url")
            or payload.get("token")
            or payload.get("encrypted_token")
            or ""
        )

    token = str(token).strip()
    if not token or len(token) > 8192:
        err = ValueError(f"Invalid token length ({len(token)} chars). Expected 1 to 8192 chars.")
        log_detailed_error("DMS DB REGISTER TOKEN VALIDATION", err, {"payload_keys": list(payload.keys()) if isinstance(payload, dict) else type(payload)})
        raise HTTPException(status_code=400, detail="Invalid, missing, or oversized database token in payload.")

    debug_print(f"[DMS DB REGISTER] Encrypted Token Length: {len(token)}")

    # Decrypt payload or use plain URL if already a valid SQLAlchemy connection string
    db_url = ""
    if re.match(r"^\w+(?:\+\w+)?:\/\/", token):
        db_url = token
        encryption_mode = "Direct Plaintext URL"
    else:
        encryption_mode = "AES-256-CBC (iv_hex:cipher_hex)" if ":" in token else "RSA-OAEP (Base64)"
        debug_print(f"[DMS DB REGISTER] Decryption Mode Selected: {encryption_mode}")

        try:
            if ":" in token:
                db_url = _decrypt_aes_hex_iv_cipher(token)
            else:
                db_url = _decrypt_rsa_b64(token)
            
            logger.info("\033[1;32m[DMS DB REGISTER DECRYPT SUCCESS]\033[0m Mode: %s | URL: \033[1;36m%s\033[0m", encryption_mode, _mask_url(db_url))
            debug_print(f"[DMS DB REGISTER] [OK] Decrypted DB URL: {_mask_url(db_url)}")
        except Exception as e:
            log_detailed_error("DMS DB REGISTER DECRYPTION", e, {"mode": encryption_mode, "token_sample": token[:30] + "..."})
            raise HTTPException(status_code=400, detail=f"Failed to decrypt payload via {encryption_mode}: {e}")

    # Sanitize missing or undefined credentials using environment configuration
    db_user = (os.environ.get("DMS_DB_USER") or "postgres").strip()
    db_pass = (os.environ.get("DMS_DB_PASSWORD") or "postgres").strip()

    if "://undefined:" in db_url or "://undefined@" in db_url or re.search(r'^(postgresql(?:\+\w+)?://)(?:@|$)', db_url):
        db_url = re.sub(r'^(postgresql(?:\+\w+)?://)(?:[^/@]+@)?', f'\\1{db_user}:{db_pass}@', db_url)
        logger.info("\033[1;33m[DMS DB REGISTER CREDENTIAL SANITIZED]\033[0m Replaced undefined/missing credentials → %s", _mask_url(db_url))
        debug_print(f"[DMS DB REGISTER] Sanitized Credentials → {_mask_url(db_url)}")

    # Validate SQLAlchemy DB URL regex format
    if not re.match(r"^\w+(?:\+\w+)?:\/\/", db_url):
        err = ValueError(f"String '{_mask_url(db_url)[:50]}' failed SQLAlchemy database URL regex check.")
        log_detailed_error("DMS DB REGISTER INVALID URL FORMAT", err, {"db_url": _mask_url(db_url)})
        raise HTTPException(status_code=400, detail="Decrypted value is not a valid SQLAlchemy database URL.")

    staff_uid = _header(request, "x-staff-uid", "x_staff_uid")
    if not staff_uid:
        raise HTTPException(status_code=401, detail="X-Staff-UID is required for database registration.")
    session_uid = str(uuid.uuid4())
    logger.info("\033[1;34m[DMS DB REGISTER HEADERS]\033[0m Staff UID: %s | Session UUID issued: %s", staff_uid, session_uid)
    debug_print(f"[DMS DB REGISTER] Staff UID: {staff_uid} | Session UUID issued: {session_uid}")

    # Save session
    ok = save_session_db_url(session_uid, db_url, staff_uid=staff_uid)
    if not ok:
        err = RuntimeError(f"save_session_db_url returned False for session_uid={session_uid}")
        log_detailed_error("DMS DB REGISTER SESSION SAVE", err, {"session_uid": session_uid, "staff_uid": staff_uid, "db_url": _mask_url(db_url)})
        raise HTTPException(status_code=500, detail="Failed to save database session.")

    logger.info("\033[1;32m[DMS DB REGISTER COMPLETE]\033[0m Session UUID: \033[1;33m%s\033[0m | Staff UID: %s | DB URL: \033[1;36m%s\033[0m", session_uid, staff_uid, _mask_url(db_url))
    debug_print(f"[DMS DB REGISTER] [SUCCESS] Session UUID={session_uid} for staff_uid={staff_uid}")
    debug_print(f"[DMS DB REGISTER] Final Response Payload: {{'ok': True, 'uid': '{session_uid}', 'staff_uid': '{staff_uid}'}}")
    debug_print("=" * 80 + "\n")

    return {"ok": True, "uid": session_uid, "x_uid": session_uid, "staff_uid": staff_uid}


@router.get("/crypto/public-key")
def get_rsa_public_key():
    """
    Returns the RSA public key (PEM) for encrypting the DB URL via RSA-OAEP.
    """
    logger.info("\033[1;34m[CRYPTO PUBLIC KEY REQUEST]\033[0m Serving RSA Public Key PEM")
    from cryptography.hazmat.primitives import serialization
    pub_pem = _get_rsa_private_key().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return {"public_key_pem": pub_pem}
