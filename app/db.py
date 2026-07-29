"""
Shared Postgres connection pool for the product tables (users / conversations / messages).

The pool is created once in main.py's lifespan and registered here, so any module can
borrow a connection without opening a second pool to Neon.
"""
# --- Imports ---
from psycopg_pool import AsyncConnectionPool

pool: AsyncConnectionPool | None = None


def set_pool(p: AsyncConnectionPool) -> None:
    global pool
    pool = p


def get_pool() -> AsyncConnectionPool:
    if pool is None:
        raise RuntimeError("DB pool not initialised — is the app started?")
    return pool