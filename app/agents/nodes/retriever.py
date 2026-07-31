# --- Imports: standard library ---
import asyncio

# --- Imports: third-party ---
import logfire

# --- Imports: local application ---
from app.agents.state import AgentState
from app.config import settings
from app.services.retrieval.qdrant_service import search_enterprise_knowledge
from app.services.retrieval.ranking_service import rerank_documents


async def retrieve_node(state: AgentState):
    """
    Performs vector search and semantic reranking for technical queries.
    """
    query = state["current_query"]


    # Standard Retrieval Logic
    with logfire.span("🔍 Knowledge Retrieval"):
        logfire.info(f"Searching Qdrant for: {query}")
        raw_results = await search_enterprise_knowledge(query, limit=15)
        logfire.info(f"Retrieved {len(raw_results)} candidates from Vector DB")

        doc_contents = [doc['content'] for doc in raw_results]

        if settings.RERANK_ENABLED:
            with logfire.span("⚖️ Semantic Reranking"):
                # FlashRank is CPU-bound (no async twin exists) — run it on a helper
                # thread so the event loop keeps serving other requests meanwhile.
                reranked_contents = await asyncio.to_thread(
                    rerank_documents, query, doc_contents, top_n=5
                )
                logfire.info("Reranking complete. Kept top 5 most relevant chunks.")
        else:
            # Skips rerank_documents() entirely, so FlashRank's Ranker() never
            # gets constructed and its ONNX model never loads into memory —
            # not just a faster no-op, an actual avoided allocation.
            reranked_contents = doc_contents[:5]
            logfire.info("⚠️ Reranking disabled (RERANK_ENABLED=false) — using raw Qdrant order.")

        formatted_docs = [f"CONTENT: {doc}" for doc in reranked_contents]

    return {
        "documents": formatted_docs,
        "status": f"Found technical context.",
        "plan": state["plan"] + ["Context Retrieved"]
    }
