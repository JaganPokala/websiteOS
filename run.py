"""
Local Windows launcher.

Why this file exists:
On Windows, Python's default asyncio event loop ("Proactor") does not support
the socket operations psycopg (the Postgres driver) relies on, so the
AsyncPostgresSaver crashes at startup with:
    Psycopg cannot use the 'ProactorEventLoop' to run in async mode.

Setting the Selector policy alone is not enough — uvicorn.run() builds its own
event loop and ignores the ambient policy. So we create the loop ourselves
(asyncio.run below, which respects the policy) and run uvicorn's server
coroutine on it directly.

Linux/Docker does not have this problem — there, the plain
    uvicorn app.main:app --host 0.0.0.0 --port 8080
from the Dockerfile still works unchanged.
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Windows consoles default to a legacy encoding (cp1252) that cannot print
    # the emoji used in our logfire messages — force UTF-8 so logs don't error.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import uvicorn


async def main() -> None:
    # Optional port argument so multiple instances can run side by side:
    #   python run.py        -> port 8000
    #   python run.py 8001   -> port 8001
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=port)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
