from __future__ import annotations
import json
import os
import threading
import logging
from pathlib import Path
from typing import Any, Dict, Set, List

logger = logging.getLogger("dms.user_prefs.service")

VALID_THIRD_LANGS: set[str] = {
    "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN",
    "gu-IN", "pa-IN", "bn-IN", "ur-IN",
}

DEFAULT_THIRD_LANG = "ta-IN"

# ── Output text language (answer LLM) ────────────────────────────────────────
# "auto" = reply in whatever language the user asked in (current behavior).
OUTPUT_LANG_LABELS: dict[str, str] = {
    "auto":  "Auto — match question",
    "en-IN": "English",
    "hi-IN": "हिन्दी Hindi",
    "ta-IN": "தமிழ் Tamil",
    "te-IN": "తెలుగు Telugu",
    "kn-IN": "ಕನ್ನಡ Kannada",
    "ml-IN": "മലയാളം Malayalam",
    "mr-IN": "मराठी Marathi",
    "bn-IN": "বাংলা Bengali",
    "gu-IN": "ગુજરાતી Gujarati",
    "pa-IN": "ਪੰਜਾਬੀ Punjabi",
    "ur-IN": "اردو Urdu",
}
VALID_OUTPUT_LANGS: set[str] = set(OUTPUT_LANG_LABELS.keys())
DEFAULT_OUTPUT_LANG = "auto"

VALID_OUTPUT_SCRIPTS: set[str] = {"native", "roman"}
DEFAULT_OUTPUT_SCRIPT = "native"


_LOCK = threading.Lock()

def _get_aes_key() -> bytes:
    key_hex = (os.environ.get("DMS_AES_KEY_HEX") or "").strip()
    if not key_hex or len(key_hex) != 64:
        import hashlib
        return hashlib.sha256(b"dms_at_rest_user_prefs_encrypted_key_v1").digest()
    try:
        return bytes.fromhex(key_hex)
    except Exception:
        import hashlib
        return hashlib.sha256(b"dms_at_rest_user_prefs_encrypted_key_v1").digest()

def _encrypt_data(plaintext: str) -> str:
    """Encrypt plaintext preferences JSON payload using AES-256-CBC (OWASP A02:2021 compliant)."""
    key = _get_aes_key()
    iv = os.urandom(16)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding as sym_padding
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        padder = sym_padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
        ct = encryptor.update(padded_data) + encryptor.finalize()
        return f"{iv.hex()}:{ct.hex()}"
    except Exception as e:
        logger.error("[USER_PREFS_ENCRYPT_FAIL] %s", e)
        return ""

def _decrypt_data(token: str) -> str:
    """Decrypt AES-256-CBC token -> plaintext JSON string."""
    if not token or ":" not in token:
        return ""
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
        logger.error("[USER_PREFS_DECRYPT_FAIL] %s", e)
        return ""

def _enc_prefs_path() -> Path:
    try:
        from ..config.settings import settings
        return Path(settings.BASE_DIR) / ".user_prefs.enc"
    except Exception:
        return Path(__file__).parent.parent.parent / ".user_prefs.enc"

def _legacy_prefs_path() -> Path:
    try:
        from ..config.settings import settings
        return Path(settings.BASE_DIR) / "user_prefs.json"
    except Exception:
        return Path(__file__).parent.parent.parent / "user_prefs.json"

def _load_all() -> Dict[str, Any]:
    enc_path = _enc_prefs_path()
    try:
        if enc_path.exists():
            token = enc_path.read_text(encoding="utf-8").strip()
            plain = _decrypt_data(token)
            if plain:
                data = json.loads(plain)
                return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("[USER_PREFS_LOAD_ENC_FAIL] %s", e)

    # Legacy fallback & migration
    legacy_path = _legacy_prefs_path()
    try:
        if legacy_path.exists():
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Save encrypted immediately to migrate
                    _save_all(data)
                    return data
    except Exception:
        pass
    return {}

def _save_all(data: Dict[str, Any]) -> None:
    enc_path = _enc_prefs_path()
    tmp = enc_path.with_suffix(".tmp")
    try:
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        encrypted_token = _encrypt_data(json_str)
        if encrypted_token:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(encrypted_token)
            os.replace(tmp, enc_path)
            try:
                os.chmod(enc_path, 0o600)
            except Exception:
                pass
            # Remove unencrypted legacy file if it exists
            legacy_path = _legacy_prefs_path()
            if legacy_path.exists():
                try:
                    legacy_path.unlink()
                except Exception:
                    pass
    except Exception as e:
        logger.error("[USER_PREFS_SAVE_FAIL] %s", e)

class UserPrefsService:
    @staticmethod
    def get_voice_lang(uid: str) -> str:
        if not uid:
            return DEFAULT_THIRD_LANG
        with _LOCK:
            data = _load_all()
        return data.get(uid, {}).get("voice_third_lang", DEFAULT_THIRD_LANG)

    @staticmethod
    def set_voice_lang(uid: str, lang: str) -> str:
        if not uid:
            return DEFAULT_THIRD_LANG
        if lang not in VALID_THIRD_LANGS:
            lang = DEFAULT_THIRD_LANG
        with _LOCK:
            data = _load_all()
            if uid not in data:
                data[uid] = {}
            data[uid]["voice_third_lang"] = lang
            _save_all(data)
        return lang

    @staticmethod
    def valid_third_langs() -> list[dict]:
        mapping = {
            "ta-IN": "Tamil", "te-IN": "Telugu", "kn-IN": "Kannada",
            "ml-IN": "Malayalam", "mr-IN": "Marathi", "gu-IN": "Gujarati",
            "pa-IN": "Punjabi", "bn-IN": "Bengali", "ur-IN": "Urdu"
        }
        return [{"code": k, "label": v} for k, v in sorted(mapping.items(), key=lambda x: x[1])]

    # ── Output text language ─────────────────────────────────────────────────
    @staticmethod
    def get_output_lang(uid: str) -> str:
        if not uid:
            return DEFAULT_OUTPUT_LANG
        with _LOCK:
            data = _load_all()
        return data.get(uid, {}).get("output_lang", DEFAULT_OUTPUT_LANG)

    @staticmethod
    def set_output_lang(uid: str, lang: str) -> str:
        if not uid:
            return DEFAULT_OUTPUT_LANG
        if lang not in VALID_OUTPUT_LANGS:
            lang = DEFAULT_OUTPUT_LANG
        with _LOCK:
            data = _load_all()
            if uid not in data:
                data[uid] = {}
            data[uid]["output_lang"] = lang
            _save_all(data)
        return lang

    @staticmethod
    def output_langs() -> list[dict]:
        return [{"code": k, "label": v} for k, v in OUTPUT_LANG_LABELS.items()]

    # ── Output script preference (native vs roman) ───────────────────────────
    @staticmethod
    def get_output_script(uid: str) -> str:
        if not uid:
            return DEFAULT_OUTPUT_SCRIPT
        with _LOCK:
            data = _load_all()
        return data.get(uid, {}).get("output_script", DEFAULT_OUTPUT_SCRIPT)

    @staticmethod
    def set_output_script(uid: str, script: str) -> str:
        if not uid:
            return DEFAULT_OUTPUT_SCRIPT
        script_clean = str(script or "").strip().lower()
        if script_clean not in VALID_OUTPUT_SCRIPTS:
            script_clean = DEFAULT_OUTPUT_SCRIPT
        with _LOCK:
            data = _load_all()
            if uid not in data:
                data[uid] = {}
            data[uid]["output_script"] = script_clean
            _save_all(data)
        return script_clean

