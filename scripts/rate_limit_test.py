"""
Fires N sequential /query requests at one port, as one user, to test the
rate limiter (app/rate_limit.py).

The limit check runs BEFORE the RAG pipeline (it's a FastAPI dependency
resolved ahead of the route body), so only requests that pass the limit
cost a real LLM call — a rejected request is instant and free.

First run — creates a fresh user, prints its credentials:
    .venv\\Scripts\\python.exe scripts/rate_limit_test.py --port 8000

Reuse the SAME user against a second port (to prove the limit is global
across workers, not per-process) by passing back what it printed:
    .venv\\Scripts\\python.exe scripts/rate_limit_test.py --port 8001 --email ... --password ...
"""
import argparse
import asyncio
import sys
import uuid

import httpx

QUESTION = "What is a Kubernetes Pod?"


async def main(port: int, email: str | None, password: str | None, count: int):
    base = f"http://127.0.0.1:{port}"
    password = password or "ratelimit-test-123"

    async with httpx.AsyncClient(timeout=60) as client:
        if email is None:
            email = f"ratelimit-{uuid.uuid4().hex[:10]}@example.com"
            r = await client.post(f"{base}/auth/signup", json={"email": email, "password": password})
            r.raise_for_status()
            print(f"Created new user -> --email {email} --password {password}")
            print("(reuse these two flags to hit a second port as the SAME user)\n")
        else:
            r = await client.post(f"{base}/auth/login", json={"email": email, "password": password})
            r.raise_for_status()
            print(f"Logged in as {email}\n")

        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        conv = await client.post(f"{base}/conversations", headers=headers)
        conv.raise_for_status()
        conversation_id = conv.json()["id"]

        print(f"Firing {count} requests at {base}/query\n")
        for i in range(1, count + 1):
            r = await client.post(
                f"{base}/query",
                headers=headers,
                json={"q": QUESTION, "conversation_id": conversation_id},
            )
            body = r.json()
            msg = body.get("detail") or (body.get("answer") or "")[:80]
            print(f"[{i}] status={r.status_code}  {msg}")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--email", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--count", type=int, default=6)
    args = parser.parse_args()
    asyncio.run(main(args.port, args.email, args.password, args.count))
