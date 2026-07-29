"""
Database logic for conversations & messages (the 'service' / repository layer).
Kept separate from the HTTP layer so add_message() can be reused by /query in Step 4.

Ownership rule: every query is scoped by user_id, so a user can never touch
another user's data even if they guess the conversation id (prevents IDOR).
"""
# --- Imports: standard library ---
from uuid import UUID

# --- Imports: third-party ---
from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

# --- Config ---
MAX_TITLE_LEN = 60


# --- Helpers ---
def _title_from(text: str) -> str:
    """Auto-title: collapse whitespace, trim to a clean, short title."""
    t = " ".join(text.strip().split())
    if not t:
        return "New chat"
    return t if len(t) <= MAX_TITLE_LEN else t[:MAX_TITLE_LEN].rstrip() + "…"


# --- Database operations ---
async def owns_conversation(pool, user_id: str, conversation_id) -> bool:
    """True if this conversation belongs to this user (ownership gate for /query)."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        return await cur.fetchone() is not None


async def create_conversation(pool: AsyncConnectionPool, user_id: str):
    async with pool.connection() as conn:
        cur = await conn.execute(
            """INSERT INTO conversations (user_id)
               VALUES (%s) RETURNING id, title, created_at, updated_at""",
            (user_id,),
        )
        return await cur.fetchone()


async def list_conversations(pool, user_id: str, limit: int, offset: int):
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT id, title, created_at, updated_at FROM conversations
               WHERE user_id = %s
               ORDER BY updated_at DESC
               LIMIT %s OFFSET %s""",
            (user_id, limit, offset),
        )
        return await cur.fetchall()


async def get_messages(pool, user_id: str, conversation_id: UUID, limit: int, offset: int):
    """Return messages, or None if the conversation isn't the caller's (→ 404)."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        if await cur.fetchone() is None:
            return None
        cur = await conn.execute(
            """SELECT id, role, content, sources, prompt_tokens, completion_tokens, created_at
               FROM messages WHERE conversation_id = %s
               ORDER BY created_at ASC, id ASC
               LIMIT %s OFFSET %s""",
            (conversation_id, limit, offset),
        )
        return await cur.fetchall()


async def rename_conversation(pool, user_id: str, conversation_id: UUID, title: str):
    async with pool.connection() as conn:
        cur = await conn.execute(
            """UPDATE conversations SET title = %s, updated_at = now()
               WHERE id = %s AND user_id = %s
               RETURNING id, title, updated_at""",
            (title, conversation_id, user_id),
        )
        return await cur.fetchone()   # None if not theirs


async def delete_conversation(pool, user_id: str, conversation_id: UUID) -> bool:
    """Delete the conversation (messages cascade) AND its LangGraph checkpoint rows."""
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                "DELETE FROM conversations WHERE id = %s AND user_id = %s RETURNING id",
                (conversation_id, user_id),
            )
            if await cur.fetchone() is None:
                return False   # not theirs / not found → 404
            # The conversation id IS the LangGraph thread_id — clean up its checkpoints.
            tid = str(conversation_id)
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                await conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (tid,))
        return True


async def add_message(pool, conversation_id: UUID, role: str, content: str,
                      sources=None, prompt_tokens=None, completion_tokens=None):
    """
    Insert a message, bump the conversation's updated_at, and auto-title from the
    first user message. Called by /query in Step 4 (not by any Step 3 endpoint yet).
    """
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO messages
                   (conversation_id, role, content, sources, prompt_tokens, completion_tokens)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (conversation_id, role, content,
                 Json(sources) if sources is not None else None,
                 prompt_tokens, completion_tokens),
            )
            await conn.execute(
                "UPDATE conversations SET updated_at = now() WHERE id = %s",
                (conversation_id,),
            )
            if role == "user":
                cur = await conn.execute(
                    "SELECT title FROM conversations WHERE id = %s", (conversation_id,)
                )
                row = await cur.fetchone()
                if row and row["title"] == "New chat":
                    await conn.execute(
                        "UPDATE conversations SET title = %s WHERE id = %s",
                        (_title_from(content), conversation_id),
                    )