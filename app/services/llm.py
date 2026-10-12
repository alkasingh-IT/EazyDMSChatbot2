"""
DMS LLM Service — Supports switching between OCI Generative AI (Google Gemini 2.5 Flash)
and Direct Google Gemini API Service (Gemini 3.0 Flash Preview) via LLM_PROVIDER setting ("oci" vs "google"),
with TTL response caching for high performance.
"""
import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from ..config.settings import settings

logger = logging.getLogger("dms.llm")
_genai_client = None

# In-memory response cache: { cache_key -> (timestamp, result) }
_LLM_RESPONSE_CACHE: Dict[str, Tuple[float, Any]] = {}

# ── Persistent HTTP connection pool for OCI OpenAI-compatible endpoint ──
# A single httpx.Client is reused across all calls, eliminating per-request
# TCP handshake + SSL negotiation (saves 150–400 ms per OCI LLM call).
_oci_http_client: "httpx.Client | None" = None
_oci_http_client_lock = threading.Lock()


def _get_oci_http_client() -> httpx.Client:
    """Return the shared httpx.Client for OCI calls, creating it on first use."""
    global _oci_http_client
    if _oci_http_client is None:
        with _oci_http_client_lock:
            if _oci_http_client is None:
                _oci_http_client = httpx.Client(
                    timeout=httpx.Timeout(60.0),
                    limits=httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=10,
                        keepalive_expiry=60.0,
                    ),
                    http2=False,
                )
                logger.info("[LLM] OCI httpx connection pool initialised (keep-alive, max=20)")
    return _oci_http_client


def _get_cache_key(provider: str, model: str, system: str, user: str, is_json: bool) -> str:
    """Generate SHA256 cache key for LLM prompt requests."""
    raw = f"{provider}:{model}:{system}:{user}:{is_json}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clear_llm_cache() -> None:
    """Clear in-memory LLM response cache."""
    _LLM_RESPONSE_CACHE.clear()
    logger.info("[LLM CACHE] In-memory response cache cleared")


def _call_oci_openai(system: str, user: str, is_json: bool = False) -> str:
    """Call OCI Generative AI OpenAI-compatible endpoint using persistent httpx pool.

    Uses a module-level httpx.Client with keep-alive connections so that
    repeated calls reuse the same TCP/TLS session instead of re-handshaking
    each time (saves 150-400 ms per call over urllib.request).
    """
    base_url = (settings.OCI_BASE_URL or "").rstrip("/")
    if not base_url:
        raise ValueError("OCI_BASE_URL is empty")

    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    api_key = settings.OCI_API_KEY
    model = settings.OCI_MODEL or "google.gemini-2.5-flash"

    messages: list = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": user + ("\n\nReturn ONLY valid JSON, no markdown code fences." if is_json else ""),
        }
    )

    payload = {
        "model": model,
        "messages": messages,
        # JSON calls (routing / chart spec) default to temperature 0 so the SAME
        # question always routes to the SAME flag — routing flip-flops at 0.2.
        "temperature": float(os.environ.get("LLM_JSON_TEMPERATURE", "0")) if is_json else 0.7,
        "max_tokens": 4000,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    client = _get_oci_http_client()
    try:
        response = client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        err_body = ""
        try:
            err_body = exc.response.text[:800]
        except Exception:
            pass
        raise RuntimeError(
            f"OCI HTTP {exc.response.status_code}: {err_body or 'no body'}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"OCI request error: {exc}") from exc

    parsed = response.json()
    choices = parsed.get("choices", [])
    if choices:
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


def call_oci_text(system: str, user: str) -> str:
    """Call OCI Generative AI directly.
    
    STRICT: Absolutely NO fallback to Gemini. If OCI fails, raises exception directly.
    """
    logger.info("[LLM] Analysis via OCI OpenAI (%s) [Strict OCI - No fallback to Gemini]", settings.OCI_MODEL)
    return _call_oci_openai(system, user, is_json=False)


def stream_oci_text(system: str, user: str):
    """Stream text from OCI Generative AI using OpenAI Responses API.
    
    STRICT: Absolutely NO fallback to Gemini.
    Uses client.responses.create(model=settings.OCI_MODEL, input=..., stream=True).
    """
    from openai import OpenAI

    base_url = (settings.OCI_BASE_URL or "").rstrip("/")
    if not base_url:
        raise ValueError("OCI_BASE_URL is empty")

    api_key = settings.OCI_API_KEY
    model = settings.OCI_MODEL or "google.gemini-2.5-flash"

    # Format input prompt
    if system:
        full_prompt = f"System Instructions:\n{system}\n\nUser Question:\n{user}"
    else:
        full_prompt = user

    logger.info("[LLM] Phase 2 Streaming via OCI OpenAI (%s) [Strict OCI - No fallback to Gemini]", model)

    client = OpenAI(base_url=base_url, api_key=api_key)

    try:
        stream = client.responses.create(
            model=model,
            input=full_prompt,
            stream=True,
        )
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", None)
                if delta:
                    yield delta
            elif hasattr(event, "delta") and isinstance(event.delta, str):
                if event.delta:
                    yield event.delta
    except Exception as exc:
        logger.warning("[LLM] OCI responses.create streaming failed: %s. Attempting chat.completions fallback...", exc)
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user})

            chat_stream = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.1,
                max_tokens=4000,
            )
            for chunk in chat_stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc2:
            # STRICT: Absolutely NO fallback to Gemini. Raise OCI error directly!
            logger.error("[LLM] OCI streaming failed completely: %s", exc2)
            raise RuntimeError(f"OCI streaming error: {exc2}") from exc2

