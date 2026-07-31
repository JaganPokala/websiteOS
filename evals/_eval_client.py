"""
Shared auth helper for the eval suite.

/query and /query/stream now require a Bearer token and a real conversation_id
(added after this eval suite was first written) — pipeline.py and
guardrails_eval.py both need the same authenticated session, so it lives here
once instead of being duplicated in both.
"""
import uuid

import requests

BASE_URL = "http://localhost:8000"

_session = {"headers": None}


def get_auth_headers() -> dict:
    """Sign up one throwaway eval user, once per process, and cache the token."""
    if _session["headers"] is None:
        email = f"eval-{uuid.uuid4().hex[:10]}@example.com"
        resp = requests.post(
            f"{BASE_URL}/auth/signup",
            json={"email": email, "password": "eval-run-password-123"},
            timeout=30,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        _session["headers"] = {"Authorization": f"Bearer {token}"}
    return _session["headers"]


def new_conversation_id() -> str:
    """
    A fresh conversation per eval sample — not one shared conversation for the
    whole run. Each golden question must be evaluated in isolation; reusing one
    conversation would let the planner see unrelated prior questions as
    conversation history, contaminating the eval.
    """
    resp = requests.post(f"{BASE_URL}/conversations", headers=get_auth_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]
