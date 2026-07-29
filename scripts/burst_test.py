"""
Phase 1 verification: fire N requests at the API at the same instant and
measure whether the server overlaps them (async working) or serializes them.

Run it (with the server already running in another terminal):
    .venv\\Scripts\\python.exe burst_test.py
"""
import asyncio
import sys
import time

import httpx

URL = "http://127.0.0.1:8000/query"

# Deliberately NOT greetings: plain "hi"/"hello" is answered by the guardrails
# gate directly and never reaches the LangGraph pipeline. These pass the gate
# and exercise the full planner -> responder path.
QUESTIONS = [
    "My name is Alex and I manage our kubernetes clusters.",
    "My name is Priya, please remember my name for later.",
    "I am a devops engineer, nice to meet you.",
    "Please remember that my favourite tool is kubectl.",
]


async def send_one(client: httpx.AsyncClient, i: int, q: str):
    t0 = time.perf_counter()
    r = await client.post(URL, json={"q": q, "thread_id": f"burst-{i}"})
    dt = time.perf_counter() - t0
    data = r.json()
    plan = " | ".join(data.get("thought_process") or [])
    return i, dt, plan


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        t0 = time.perf_counter()
        results = await asyncio.gather(
            *[send_one(client, i, q) for i, q in enumerate(QUESTIONS)]
        )
        wall = time.perf_counter() - t0

    print(f"\n{'req':<5}{'latency':<11}plan")
    for i, dt, plan in results:
        print(f"{i:<5}{dt:>6.2f}s    {plan}")

    total = sum(dt for _, dt, _ in results)
    print(f"\nsum of individual latencies : {total:6.2f}s")
    print(f"actual wall-clock time      : {wall:6.2f}s")
    print(f"overlap factor              : {total / wall:.1f}x")
    print("\nHow to read it:")
    print("  wall ≈ slowest single request -> requests overlapped (async is working)")
    print("  wall ≈ sum of all latencies   -> requests ran one-by-one (something blocks)")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
