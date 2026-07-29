"""
Phase 3 / streaming verification: hit /query/stream and print tokens AS THEY
ARRIVE. If streaming works, you'll see the answer type itself out word-by-word
with visible pauses. If it all appears at once after a long pause, tokens are
being buffered and streaming isn't actually working.

Run it (server must be running via `python run.py` in another terminal):
    .venv\\Scripts\\python.exe stream_test.py
"""
import asyncio
import json
import sys
import time

import httpx

URL = "http://127.0.0.1:8000/query/stream"


async def main():
    # payload = {"q": "How does pod autoscaling work?", "thread_id": "stream-test"}
    # payload = {"q": "what is k8s?", "thread_id": "stream-test-134"}
    # payload = {"q": "what can you do ??", "thread_id": "stream-test-2"}

    payload = {"q": "it acts as a primary control plane for distributed systems,managing the deployment, scaling, and maintenance of containerized applications", "thread_id": "stream-test-23"}

    t0 = time.perf_counter()
    first_token_at = None
    token_count = 0

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", URL, json=payload) as resp:
            print(f"status: {resp.status_code}\n")
            print("answer: ", end="", flush=True)
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[len("data: "):])
                if "token" in data:
                    if first_token_at is None:
                        first_token_at = time.perf_counter() - t0
                    token_count += 1
                    print(data["token"], end="", flush=True)
                elif data.get("done"):
                    break
                elif "error" in data:
                    print(f"\n[error: {data['error']}]")
                    break

    total = time.perf_counter() - t0
    print("\n\n---")
    print(f"tokens received      : {token_count}")
    print(f"time to first token  : {first_token_at:.2f}s" if first_token_at else "no tokens")
    print(f"total time           : {total:.2f}s")
    print("\nStreaming works if 'time to first token' is much smaller than 'total time'")
    print("AND you saw the text appear gradually rather than all at once.")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
