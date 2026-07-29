# ============================================================
# CRITICAL: logfire MUST be configured before ALL other imports
# so that spans from all modules are captured from the start.
# ============================================================
import os

import logfire
from dotenv import load_dotenv

load_dotenv()
logfire.configure(token=os.getenv("LOGFIRE_TOKEN"))

# --- Imports: standard library ---
import json
from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID

# --- Imports: third-party ---
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from app.rate_limit import enforce_rate_limit

# --- Imports: local application (app modules are already active — logfire is configured) ---
from app import db
from app.agents import graph
from app.auth import get_current_user_id, router as auth_router
from app.config import settings
from app.conversations import router as conversations_router, service as conv_service
from app.guardrails import guard, initialize_rails


# --- Lifespan (startup / shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup (before the first request) and once at shutdown.
    Startup: init guardrails, open the Postgres checkpointer, compile the graph.
    Shutdown: leaving the async-with closes the Postgres connection cleanly.
    """
    initialize_rails()

    if not settings.POSTGRES_URI:
        raise RuntimeError(
            "POSTGRES_URI is not set. Add your Postgres connection string to .env "
            "(Neon: dashboard → Connect → copy the connection string)."
        )

    # Connection POOL instead of a single connection: Neon's free tier suspends
    # the database after ~5 min idle and kills open connections. The pool
    # health-checks each connection before lending it out (check=...) and
    # silently redials dead ones, so checkpoint saves survive Neon's naps.
    # AsyncPostgresSaver: saving a checkpoint is a network call to Postgres (I/O),
    # so it must be awaitable — the sync PostgresSaver would freeze the event
    # loop on every node transition of every request.
    async with AsyncConnectionPool(
        conninfo=settings.POSTGRES_URI,
        min_size=1,
        max_size=10,
        open=False,
        check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()  # idempotent: creates its tables on first run
        graph.compile_graph(checkpointer)
        db.set_pool(pool)
        logfire.info("💾 Postgres checkpointer ready (pooled) — conversations survive restarts.")
        yield


# --- App initialization & middleware ---
app = FastAPI(title="Enterprise Agentic RAG API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(conversations_router)

# CORS: the React dev server runs on a different origin (port 5173), and browsers
# block cross-origin fetches unless we explicitly allow that origin. Middleware,
# not a dependency: it applies to every request and injects nothing.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.FRONTEND_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],   # includes Authorization — needed for your Bearer token
)


# --- Request/response models ---
class QueryRequest(BaseModel):
    q: str
    conversation_id: UUID          # this id IS the LangGraph thread_id


# --- Routes ---
@app.get("/")
def home():
    return {"message": "Enterprise LangGraph RAG API is live."}


@app.get("/graph")
def get_graph_image():
    """
    Returns the Mermaid image of the agent's workflow.
    Deliberately plain `def`: draw_mermaid_png() is a blocking call, so FastAPI
    runs this debug endpoint on a threadpool thread instead of the event loop.
    """
    try:
        png_bytes = graph.rag_agent.get_graph().draw_mermaid_png()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        return {"error": f"Could not generate graph image: {e}"}


@app.post("/query")
async def query(
    body: QueryRequest, 
    user_id: str = Depends(get_current_user_id),
    _: None = Depends(enforce_rate_limit),
):
    """
    Authenticated RAG query, bound to a conversation the caller owns.
    Persists the user message (auto-titles a new chat) and the assistant answer.
    """
    pool = db.get_pool()
    conversation_id = body.conversation_id
    q = body.q

    with logfire.span("💾 DB: Ownership Check"):
        if not await conv_service.owns_conversation(pool, user_id, conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")

    # Save the user's message first — this also auto-titles a fresh conversation.
    with logfire.span("💾 DB: Save User Message"):
        await conv_service.add_message(pool, conversation_id, "user", q)

    thread_id = str(conversation_id)
    initial_state = {
        "messages": [{"role": "user", "content": q}],
        "current_query": q,
        "documents": [],
        "plan": ["Start"],
        "status": "Initializing Graph...",
    }
    config = {"configurable": {"thread_id": thread_id}}

    try:
        rail_fired, rail_response = await guard(q)
        if rail_fired:
            with logfire.span("💾 DB: Save Assistant Message"):
                await conv_service.add_message(pool, conversation_id, "assistant", rail_response)
            return {
                "question": q, "answer": rail_response,
                "thought_process": ["Intent: Guardrails Fired", "Retrieval: Skipped"],
                "status": "Blocked by guardrails.", "sources": [],
            }

        final_output = await graph.rag_agent.ainvoke(initial_state, config=config)
        answer = final_output.get("final_answer")
        sources = final_output.get("documents", [])
        with logfire.span("💾 DB: Save Assistant Message"):
            await conv_service.add_message(pool, conversation_id, "assistant", answer, sources=sources)

        return {
            "question": q, "answer": answer,
            "thought_process": final_output.get("plan"),
            "status": final_output.get("status"), "sources": sources,
        }
    except Exception as e:
        logfire.error(f"❌ Backend Execution Failed: {e}")
        return {
            "question": q,
            "answer": "I apologize, but I encountered an internal error. Please try again later.",
            "thought_process": ["Error encountered during execution."],
            "status": "error", "sources": [],
        }


def _sse(payload: dict) -> str:
    """Format one Server-Sent Event. Every event the stream emits goes through here."""
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/query/stream")
async def query_stream(
    body: QueryRequest, 
    user_id: str = Depends(get_current_user_id),
    _: None = Depends(enforce_rate_limit),
    ):
    """
    Authenticated streaming query. Emits four kinds of SSE event:
      {"status":  "..."}  pipeline stage, so the UI isn't blank while we work
      {"sources": [...]}  the retrieved chunks, sent as soon as retrieval ends
      {"token":   "..."}  one piece of the answer
      {"done":    true}   finished
    Persists the assistant answer after the stream ends.
    """
    pool = db.get_pool()
    conversation_id = body.conversation_id
    q = body.q

    if not await conv_service.owns_conversation(pool, user_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await conv_service.add_message(pool, conversation_id, "user", q)

    thread_id = str(conversation_id)
    initial_state = {
        "messages": [{"role": "user", "content": q}],
        "current_query": q, "documents": [], "plan": ["Start"],
        "status": "Initializing Graph...",
    }
    config = {"configurable": {"thread_id": thread_id}}

    async def event_stream():
        try:
            yield _sse({"status": "Checking your question"})
            rail_fired, rail_response = await guard(q)
            if rail_fired:
                await conv_service.add_message(pool, conversation_id, "assistant", rail_response)
                yield _sse({"token": rail_response})
                yield _sse({"done": True})
                return

            yield _sse({"status": "Thinking"})

            parts = []
            # Two stream modes at once. LangGraph then yields (mode, payload) pairs:
            #   "updates"  -> {node_name: state_update} when a node FINISHES
            #   "messages" -> (chunk, metadata) for every LLM token
            # The updates let us narrate the pipeline; the messages carry the answer.
            async for mode, payload in graph.rag_agent.astream(
                initial_state, config=config, stream_mode=["updates", "messages"]
            ):
                if mode == "updates":
                    for node, update in (payload or {}).items():
                        if node == "planner":
                            # The planner decides the route, so its own output tells
                            # us which stage actually comes next.
                            conversational = (update or {}).get("current_query") == "CONVERSATIONAL"
                            yield _sse(
                                {"status": "Writing the answer" if conversational
                                 else "Searching your sites"}
                            )
                        elif node == "retriever":
                            yield _sse({"status": "Writing the answer"})
                            # Send the retrieved chunks now, not at the end, so the
                            # UI can show the sources button while the answer types.
                            docs = (update or {}).get("documents") or []
                            if docs:
                                yield _sse({"sources": docs})

                elif mode == "messages":
                    msg_chunk, metadata = payload
                    if metadata.get("langgraph_node") == "responder" and msg_chunk.content:
                        parts.append(msg_chunk.content)
                        yield _sse({"token": msg_chunk.content})

            answer = "".join(parts)
            # Pull sources from the final graph state, then persist the assistant message.
            snap = await graph.rag_agent.aget_state(config)
            sources = snap.values.get("documents", []) if snap else []
            await conv_service.add_message(pool, conversation_id, "assistant", answer, sources=sources)

            yield _sse({"done": True})
        except Exception as e:
            # logfire.exception captures the full traceback, not just the message.
            logfire.exception(f"❌ Streaming failed: {type(e).__name__}: {e}")
            yield _sse({"error": f"{type(e).__name__}: {e}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
