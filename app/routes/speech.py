import base64
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, Request

from ..config.settings import settings
from ..services.user_prefs import UserPrefsService, VALID_THIRD_LANGS, DEFAULT_THIRD_LANG

router = APIRouter(prefix="/api", tags=["speech"])
speech_router = router

FIXED_PRIMARY = "en-IN"
FIXED_ALT     = "hi-IN"

def _build_lang_config(third_lang: str) -> Dict:
    alt_langs = [FIXED_ALT]
    if third_lang and third_lang not in (FIXED_PRIMARY, FIXED_ALT):
        alt_langs.append(third_lang)
    return {
        "primary": FIXED_PRIMARY,
        "alt_langs": alt_langs,
        "model": "latest_short",
        "use_enhanced": True,
    }

@router.get("/speech/lang-pref")
async def get_lang_pref(uid: Optional[str] = None, x_uid: Optional[str] = Header(None)) -> Dict[str, Any]:
    resolved_uid = (uid or x_uid or "").strip()
    third_lang = UserPrefsService.get_voice_lang(resolved_uid)
    return {
        "uid": resolved_uid,
        "third_lang": third_lang,
        "fixed_primary": FIXED_PRIMARY,
        "fixed_alt": FIXED_ALT,
        "available_langs": UserPrefsService.valid_third_langs(),
        "pref_set": bool(resolved_uid and UserPrefsService.get_voice_lang(resolved_uid) in VALID_THIRD_LANGS),
    }

@router.post("/speech/lang-pref")
async def set_lang_pref(req: Request, x_uid: Optional[str] = Header(None)) -> Dict[str, Any]:
    payload = await req.json()
    uid = (payload.get("uid") or x_uid or "").strip()
    third_lang = (payload.get("third_lang") or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")
    if third_lang not in VALID_THIRD_LANGS:
        raise HTTPException(status_code=422, detail="Invalid third_lang")
    saved = UserPrefsService.set_voice_lang(uid, third_lang)
    return {"ok": True, "uid": uid, "third_lang": saved, "fixed_primary": FIXED_PRIMARY, "fixed_alt": FIXED_ALT}

import logging
logger = logging.getLogger("dms.speech")

@router.post("/speech/transcribe")
async def transcribe(req: Request, x_uid: Optional[str] = Header(None)) -> Dict[str, Any]:
    payload = await req.json()
    audio_b64 = (payload.get("audio_b64") or "").strip()
    if not audio_b64:
        raise HTTPException(status_code=400, detail="audio_b64 is required")
    try:
        sample_rate_hz = int(payload.get("sample_rate_hz") or 16000)
    except Exception:
        sample_rate_hz = 16000

    uid = (payload.get("uid") or x_uid or "").strip()
    third_lang = UserPrefsService.get_voice_lang(uid) if uid else DEFAULT_THIRD_LANG
    lang_cfg = _build_lang_config(third_lang)

    logger.info(
        "\033[1;94m[SPEECH DECODING REQUEST]\033[0m User ID: \033[1;33m%s\033[0m | Config: primary=%s, alts=%s | Audio Payload: %d bytes",
        uid or "Anonymous", lang_cfg.get("primary"), lang_cfg.get("alt_langs"), len(audio_b64)
    )

    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64")

    res = _transcribe_google_cloud(audio_bytes, sample_rate_hz, lang_cfg)
    logger.info(
        "\033[1;94m[SPEECH DECODED RESULT]\033[0m User ID: %s | Transcript: '\033[1;33m%s\033[0m' | Language: %s | Confidence: %.2f",
        uid or "Anonymous", res.get("transcript", ""), res.get("language", "en-IN"), res.get("confidence", 0.0)
    )
    return res


def _transcribe_google_cloud(audio_bytes: bytes, sample_rate_hz: int, lang_cfg: Dict) -> Dict[str, Any]:
    primary_lang = lang_cfg["primary"]
    alt_langs    = lang_cfg["alt_langs"]
    model        = lang_cfg.get("model", "latest_short")
    use_enhanced = lang_cfg.get("use_enhanced", True)

    try:
        from google.cloud import speech_v1
        from google.oauth2 import service_account

        creds_dict = getattr(settings, "GOOGLE_CLOUD_CREDENTIALS_DICT", None)
        if creds_dict:
            credentials = service_account.Credentials.from_service_account_info(creds_dict)
            client = speech_v1.SpeechClient(credentials=credentials)
        else:
            client = speech_v1.SpeechClient()
    except Exception as e:
        return {
            "ok": False,
            "transcript": "",
            "error": f"Google Cloud Speech client initialization error: {str(e)}",
            "requested_language": primary_lang
        }

    if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        wav_info = _read_wav_format(audio_bytes)
        sample_rate_hz = wav_info["sample_rate"]
        audio_data = _extract_wav_audio(audio_bytes)
        if wav_info["channels"] == 2:
            audio_data = _stereo_to_mono(audio_data)
    else:
        audio_data = audio_bytes

    audio_data = _normalize_audio(audio_data)
    audio_data = _trim_silence(audio_data, sample_rate_hz)
    audio_data = _noise_gate(audio_data, threshold=200)

    audio_obj = speech_v1.RecognitionAudio(content=audio_data)
    attempts = [
        (model, use_enhanced, speech_v1.RecognitionConfig.AudioEncoding.LINEAR16),
        ("default", True, speech_v1.RecognitionConfig.AudioEncoding.LINEAR16),
        ("default", False, speech_v1.RecognitionConfig.AudioEncoding.LINEAR16),
    ]

    for attempt_model, attempt_enhanced, encoding in attempts:
        config = speech_v1.RecognitionConfig(
            encoding=encoding,
            sample_rate_hertz=sample_rate_hz,
            language_code=primary_lang,
            alternative_language_codes=alt_langs,
            enable_automatic_punctuation=True,
            model=attempt_model,
            use_enhanced=attempt_enhanced,
            max_alternatives=3,
        )
        try:
            response = client.recognize(config=config, audio=audio_obj)
        except Exception:
            continue

        transcript = ""
        confidence_scores = []
        for result in response.results:
            if result.alternatives:
                best = result.alternatives[0]
                if best.transcript.strip():
                    transcript += best.transcript + " "
                    confidence_scores.append(best.confidence)

        transcript = transcript.strip()
        if response.results:
            avg_conf = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
            detected_lang = response.results[0].language_code or primary_lang
            return {
                "ok": True,
                "transcript": transcript,
                "confidence": avg_conf,
                "model": attempt_model,
                "language": detected_lang,
                "requested_language": primary_lang,
            }

    return {"ok": True, "transcript": "", "confidence": 0.0, "warning": "No speech detected"}

def _read_wav_format(wav_bytes: bytes) -> dict:
    import struct
    try:
        pos = 12
        while pos < len(wav_bytes) - 8:
            chunk_id = wav_bytes[pos:pos + 4]
            chunk_size = struct.unpack("<I", wav_bytes[pos + 4:pos + 8])[0]
            if chunk_id == b"fmt ":
                fmt = pos + 8
                channels = struct.unpack("<H", wav_bytes[fmt + 2:fmt + 4])[0]
                sample_rate = struct.unpack("<I", wav_bytes[fmt + 4:fmt + 8])[0]
                bits_per_sample = struct.unpack("<H", wav_bytes[fmt + 14:fmt + 16])[0]
                return {"channels": channels, "sample_rate": sample_rate, "bits_per_sample": bits_per_sample}
            pos += 8 + chunk_size
    except Exception:
        pass
    return {"channels": 1, "sample_rate": 16000, "bits_per_sample": 16}

def _extract_wav_audio(wav_bytes: bytes) -> bytes:
    import struct
    try:
        pos = 12
        while pos < len(wav_bytes) - 8:
            chunk_id = wav_bytes[pos:pos + 4]
            chunk_size = struct.unpack("<I", wav_bytes[pos + 4:pos + 8])[0]
            if chunk_id == b"data":
                return wav_bytes[pos + 8: pos + 8 + chunk_size]
            pos += 8 + chunk_size
    except Exception:
        pass
    return wav_bytes

def _stereo_to_mono(audio_bytes: bytes) -> bytes:
    import struct
    mono = bytearray()
    for i in range(0, len(audio_bytes) - 3, 4):
        left = struct.unpack("<h", audio_bytes[i:i + 2])[0]
        right = struct.unpack("<h", audio_bytes[i + 2:i + 4])[0]
        sample = int((left + right) / 2)
        sample = max(-32768, min(32767, sample))
        mono.extend(struct.pack("<h", sample))
    return bytes(mono)

def _normalize_audio(audio_data: bytes) -> bytes:
    import struct
    if len(audio_data) < 4: return audio_data
    sample_window = min(len(audio_data), 4000)
    samples = [abs(struct.unpack("<h", audio_data[i:i + 2])[0]) for i in range(0, sample_window - 1, 2)]
    if not samples: return audio_data
    max_val = max(samples)
    if max_val < 1000 and max_val >= 100:
        factor = min(8000 / max(max_val, 1), 30.0)
        return _amplify_audio(audio_data, factor)
    return audio_data

def _amplify_audio(audio_bytes: bytes, factor: float) -> bytes:
    import struct
    amplified = bytearray()
    for i in range(0, len(audio_bytes) - 1, 2):
        sample = struct.unpack("<h", audio_bytes[i:i + 2])[0]
        s = max(-32768, min(32767, int(sample * factor)))
        amplified.extend(struct.pack("<h", s))
    return bytes(amplified)

def _trim_silence(audio_bytes: bytes, sample_rate_hz: int) -> bytes:
    import struct
    if len(audio_bytes) < 4: return audio_bytes
    frame_size = max(4, int(0.03 * sample_rate_hz) * 2)
    num_frames = max(1, len(audio_bytes) // frame_size)
    is_speech = [False] * num_frames
    for f in range(num_frames):
        start, end = f * frame_size, min((f + 1) * frame_size, len(audio_bytes))
        count = (end - start) // 2
        if count > 0:
            avg = sum(abs(struct.unpack("<h", audio_bytes[k:k + 2])[0]) for k in range(start, end - 1, 2)) / count
            is_speech[f] = avg >= 120
    try:
        first_speech = is_speech.index(True)
        last_speech = len(is_speech) - 1 - is_speech[::-1].index(True)
    except ValueError:
        return audio_bytes
    return audio_bytes[max(0, first_speech - 2) * frame_size: min(len(is_speech), last_speech + 3) * frame_size]

def _noise_gate(audio_bytes: bytes, threshold: int = 200) -> bytes:
    import struct
    if len(audio_bytes) < 4: return audio_bytes
    cleaned = bytearray()
    for i in range(0, len(audio_bytes) - 1, 2):
        sample = struct.unpack("<h", audio_bytes[i:i + 2])[0]
        cleaned.extend(b"\x00\x00" if abs(sample) < threshold else struct.pack("<h", sample))
    return bytes(cleaned)
