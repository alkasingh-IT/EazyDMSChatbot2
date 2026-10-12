"""
DMS LLM Service — Supports switching between OCI Generative AI (Google Gemini 2.5 Flash)
and Direct Google Gemini API Service (Gemini 3.0 Flash Preview) via LLM_PROVIDER setting ("oci" vs "google"),
with TTL response caching for high performance.
"""
import hashlib
import json
import logging
import re
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

from ..config.settings import settings

logger = logging.getLogger("dms.llm")
_genai_client = None

# In-memory response cache: { cache_key -> (timestamp, result) }
_LLM_RESPONSE_CACHE: Dict[str, Tuple[float, Any]] = {}


def _get_cache_key(provider: str, model: str, system: str, user: str, is_json: bool) -> str:
    """Generate SHA256 cache key for LLM prompt requests."""
    raw = f"{provider}:{model}:{system}:{user}:{is_json}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clear_llm_cache() -> None:
    """Clear in-memory LLM response cache."""
    _LLM_RESPONSE_CACHE.clear()
    logger.info("[LLM CACHE] In-memory response cache cleared")


def _call_oci_openai(system: str, user: str, is_json: bool = False) -> str:
    """Call OCI Generative AI OpenAI-compatible endpoint for Google Gemini 2.5 Flash."""
    base_url = (settings.OCI_BASE_URL or "").rstrip("/")
    if not base_url:
        raise ValueError("OCI_BASE_URL is empty")

    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    api_key = settings.OCI_API_KEY
    model = settings.OCI_MODEL or "google.gemini-2.5-flash"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user + ("\n\nReturn ONLY valid JSON, no markdown code fences." if is_json else "")})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2 if is_json else 0.7,
        "max_tokens": 4000,
    }

    req_data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp_body = resp.read().decode("utf-8")
        parsed = json.loads(resp_body)
        choices = parsed.get("choices", [])
        if choices and len(choices) > 0:
            content = choices[0].get("message", {}).get("content", "")
            return content or ""
        return ""


def _call_genai_sdk(system: str, user: str, is_json: bool = False) -> str:
    """Call Direct Google Gemini API Service using google.genai SDK (Gemini 3 Flash Preview)."""
    global _genai_client
    if _genai_client is None:
        from google import genai
        _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)

    model = settings.GEMINI_MODEL or "gemini-3-flash-preview"
    prompt = f"{system}\n\n{user}" if system else user
    if is_json:
        prompt += "\n\nReturn ONLY valid JSON, no markdown code fences."
    resp = _genai_client.models.generate_content(
        model=model,
        contents=prompt,
    )
    return (resp.text or "").strip()


def call_llm_text(system: str, user: str) -> str:
    """Call selected LLM provider and return text response with caching."""
    provider = settings.LLM_PROVIDER.lower()
    model = settings.GEMINI_MODEL if provider in ("google", "genai", "direct_gemini") else settings.OCI_MODEL
    cache_key = _get_cache_key(provider, model, system, user, is_json=False)

    # Check cache
    ttl = getattr(settings, "LLM_CACHE_TTL", 300)
    now = time.time()
    if cache_key in _LLM_RESPONSE_CACHE:
        ts, cached_text = _LLM_RESPONSE_CACHE[cache_key]
        if now - ts <= ttl:
            logger.info("[LLM CACHE HIT] Returning cached text response (age=%.1fs)", now - ts)
            return cached_text

    if provider in ("google", "genai", "direct_gemini"):
        logger.info("[LLM] call_llm_text | Provider=GOOGLE (Direct Gemini) | Model=%s", model)
        try:
            text = _call_genai_sdk(system, user, is_json=False)
            logger.info("[LLM] call_llm_text OK (Google GenAI) | response_len=%d", len(text))
            _LLM_RESPONSE_CACHE[cache_key] = (now, text)
            return text
        except Exception as err:
            logger.warning("[LLM WARNING] Google GenAI call failed: %s. Fallback to OCI OpenAI...", err)
            try:
                text = _call_oci_openai(system, user, is_json=False)
                _LLM_RESPONSE_CACHE[cache_key] = (now, text)
                return text
            except Exception as e2:
                logger.error("[LLM ERROR] Both providers failed: %s", e2, exc_info=True)
                return "I wasn't able to get a response right now. Please try again in a moment."
    else:
        # Default OCI Generative AI
        logger.info("[LLM] call_llm_text | Provider=OCI (Gemini 2.5 Flash) | Model=%s | Region=%s",
                    model, settings.OCI_REGION)
        try:
            text = _call_oci_openai(system, user, is_json=False)
            logger.info("[LLM] call_llm_text OK (OCI OpenAI) | response_len=%d", len(text))
            _LLM_RESPONSE_CACHE[cache_key] = (now, text)
            return text
        except Exception as oci_err:
            logger.warning("[LLM WARNING] OCI call failed: %s. Fallback to Google GenAI...", oci_err)
            try:
                text = _call_genai_sdk(system, user, is_json=False)
                _LLM_RESPONSE_CACHE[cache_key] = (now, text)
                return text
            except Exception as e2:
                logger.error("[LLM ERROR] Both providers failed: %s", e2, exc_info=True)
                return "I wasn't able to get a response right now. Please try again in a moment."


def call_llm_json(system: str, user: str) -> Any:
    """Call selected LLM provider expecting JSON response with caching."""
    provider = settings.LLM_PROVIDER.lower()
    model = settings.GEMINI_MODEL if provider in ("google", "genai", "direct_gemini") else settings.OCI_MODEL
    cache_key = _get_cache_key(provider, model, system, user, is_json=True)

    # Check cache
    ttl = getattr(settings, "LLM_CACHE_TTL", 300)
    now = time.time()
    if cache_key in _LLM_RESPONSE_CACHE:
        ts, cached_json = _LLM_RESPONSE_CACHE[cache_key]
        if now - ts <= ttl:
            logger.info("[LLM CACHE HIT] Returning cached JSON response (age=%.1fs)", now - ts)
            return cached_json

    text = ""
    if provider in ("google", "genai", "direct_gemini"):
        logger.info("[LLM] call_llm_json | Provider=GOOGLE (Direct Gemini) | Model=%s", model)
        try:
            text = _call_genai_sdk(system, user, is_json=True)
        except Exception as err:
            logger.warning("[LLM WARNING] Google GenAI failed: %s. Fallback to OCI OpenAI...", err)
            try:
                text = _call_oci_openai(system, user, is_json=True)
            except Exception as e2:
                logger.error("[LLM ERROR] Both providers failed: %s", e2, exc_info=True)
                return {}
    else:
        # Default OCI Generative AI
        logger.info("[LLM] call_llm_json | Provider=OCI (Gemini 2.5 Flash) | Model=%s | Region=%s",
                    model, settings.OCI_REGION)
        try:
            text = _call_oci_openai(system, user, is_json=True)
        except Exception as oci_err:
            logger.warning("[LLM WARNING] OCI call failed: %s. Fallback to Google GenAI...", oci_err)
            try:
                text = _call_genai_sdk(system, user, is_json=True)
            except Exception as e2:
                logger.error("[LLM ERROR] Both providers failed: %s", e2, exc_info=True)
                return {}

    try:
        cleaned_text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
        parsed = json.loads(cleaned_text)
        logger.info("[LLM] call_llm_json parsed OK: %s", str(parsed)[:300])
        _LLM_RESPONSE_CACHE[cache_key] = (now, parsed)
        return parsed
    except Exception as parse_err:
        logger.error("[LLM ERROR] Failed to parse JSON response: %s | Raw text: %s", parse_err, text[:300])
        return {}




