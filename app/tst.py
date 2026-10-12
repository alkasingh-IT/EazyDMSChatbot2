#!/usr/bin/env python3
"""End-to-end DMS registration, UUID auth, history, and chat test.

Linux usage:
  export DMS_TEST_DB_URL='postgresql://postgres:postgres@localhost:5432/mdh_uat'
  export DMS_TEST_STAFF_UID='80'
  python3 test_dms_registration.py --base-url http://127.0.0.1:13000

The database URL is encrypted with the server public key before registration.
It is never written to disk by this script.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


def request_json(base_url: str, path: str, method: str = "GET", payload=None, headers=None, timeout=30):
    body = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base_url.rstrip("/") + path, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw": raw}
        return error.code, data


def encrypt_with_public_key(public_key_pem: str, db_url: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    encrypted = public_key.encrypt(
        db_url.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode("ascii")


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise RuntimeError(f"FAIL: {label}{': ' + detail if detail else ''}")
    print(f"PASS: {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("DMS_TEST_BASE_URL", "http://127.0.0.1:13000"))
    parser.add_argument("--staff-uid", default=os.environ.get("DMS_TEST_STAFF_UID", ""))
    parser.add_argument("--chat", action="store_true", help="Run a real analytics chat request")
    args = parser.parse_args()

    db_url = os.environ.get("DMS_TEST_DB_URL", "").strip()
    if not db_url:
        print("Set DMS_TEST_DB_URL before running this test.", file=sys.stderr)
        return 2
    if not args.staff_uid:
        print("Set DMS_TEST_STAFF_UID before running this test.", file=sys.stderr)
        return 2

    print(f"Testing server: {args.base_url}")
    print(f"Testing staff UID: {args.staff_uid}")
    print("Database URL: supplied in memory and encrypted before transmission")

    status, health = request_json(args.base_url, "/health")
    check("server health", status == 200, str(health))

    status, key_response = request_json(args.base_url, "/api/crypto/public-key")
    check("RSA public key", status == 200 and bool(key_response.get("public_key_pem")), str(key_response))

    encrypted_url = encrypt_with_public_key(key_response["public_key_pem"], db_url)
    status, registration = request_json(
        args.base_url,
        "/api/db/register",
        method="POST",
        payload={"encrypted_db_url_b64": encrypted_url},
        headers={"X-Staff-UID": args.staff_uid},
    )
    check("database registration", status == 200 and registration.get("ok") is True, str(registration))

    session_uid = registration.get("uid") or registration.get("x_uid")
    try:
        uuid.UUID(str(session_uid))
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError(f"FAIL: registration did not return a valid UUID: {session_uid!r}")
    print(f"Issued session UUID: {session_uid}")

    status, _ = request_json(args.base_url, "/api/chat/history")
    check("reject missing authentication", status == 401)

    status, _ = request_json(
        args.base_url,
        "/api/chat/history",
        headers={"X-UID": str(uuid.uuid4()), "X-Staff-UID": args.staff_uid},
    )
    check("reject invalid session UUID", status == 401)

    auth_headers = {"X-UID": str(session_uid), "X-Staff-UID": args.staff_uid}
    status, history = request_json(args.base_url, "/api/chat/history", headers=auth_headers)
    check("authenticated history request", status == 200 and isinstance(history.get("sessions"), list), str(history))

    if args.chat:
        status, chat = request_json(
            args.base_url,
            "/api/chat",
            method="POST",
            headers=auth_headers,
            payload={
                "userid": args.staff_uid,
                "message": "Secondary sales this month",
                "history": [],
            },
            timeout=180,
        )
        check("authenticated chat request", status == 200 and bool(chat.get("answer")), str(chat))
        check("chat history session returned", bool(chat.get("session_id")), str(chat))
        status, history = request_json(args.base_url, "/api/chat/history", headers=auth_headers)
        check("chat persisted in history", status == 200 and len(history.get("sessions", [])) > 0, str(history))

    print("ALL REQUEST/AUTH TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
