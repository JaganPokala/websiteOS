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
    sites = state.get("sites") or []

    with logfire.span("🔍 Knowledge Retrieval"):
        logfire.info(f"Searching Qdrant for: {query}")

        # STEP 1: unchanged — raw_results is already a list of dicts carrying
        #         content / url / title / site / heading / score.
        raw_results = await search_enterprise_knowledge(query, limit= max(15 , 10*len(sites)), sites=sites)
        logfire.info(f"Retrieved {len(raw_results)} candidates from Vector DB")

        # STEP 2: bail out early if nothing came back, so the branches below
        #         don't have to care about the empty case.
        if not raw_results:
            logfire.warning("No candidates from Qdrant — nothing to rerank.")
            return {
                "documents": [],
                "status": "No relevant context found.",
                "plan": state["plan"] + ["Context Retrieved"],
            }

        # STEP 3: FlashRank only takes strings, so pull the text out — but keep
        #         `raw_results` intact. This list is scratch, NOT the thing you
        #         return. That distinction is the whole fix: the old code let
        #         this list become the output and the urls died with it.
        doc_contents = [doc["content"] for doc in raw_results]

        # STEP 4: both branches must produce INDICES into raw_results, so they
        #         converge on one mapping line afterwards.
        #
        #   if settings.RERANK_ENABLED:
        #       order = await asyncio.to_thread(rerank_documents, query, doc_contents, top_n=5)
        #   else:
        #       # keep the existing comment about FlashRank never being constructed
        #       order = list(range(min(5, len(raw_results))))
        #
        #   Note the else branch is now range(...), not a slice of text — it has
        #   to speak the same language as rerank_documents or STEP 5 breaks on
        #   exactly the path you took to make things simpler.
        if settings.RERANK_ENABLED:
            with logfire.span("⚖️ Semantic Reranking"):
                # FlashRank is CPU-bound (no async twin exists) — run it on a helper
                # thread so the event loop keeps serving other requests meanwhile.
                order = await asyncio.to_thread(
                    rerank_documents, query, doc_contents, top_n=5
                )
                logfire.info("Reranking complete. Kept top 5 most relevant chunks.")
        else:
            # Skips rerank_documents() entirely, so FlashRank's Ranker() never
            # gets constructed and its ONNX model never loads into memory —
            # not just a faster no-op, an actual avoided allocation.
            order = list(range(min(5, len(raw_results))))
            logfire.info("⚠️ Reranking disabled (RERANK_ENABLED=false) — using raw Qdrant order.")

        # STEP 5: map indices back to the FULL records, preserving rank order:
        documents = [raw_results[i] for i in order]
        
        # STEP 6: DELETE the old line
        #             formatted_docs = [f"CONTENT: {doc}" for doc in reranked_contents]
        #         Two reasons:
        #         (a) with dicts it would stringify the dict into the prompt —
        #             "CONTENT: {'content': 'Binary expon...', 'url': ...}" — which
        #             does NOT crash, it just quietly poisons the context.
        #         (b) prompt formatting belongs to the responder, not the retriever.
        #             The retriever's job is to return data; how it is rendered into
        #             a prompt is the responder's decision.

    return {
        "documents": documents,          # now List[dict], not List[str]
        "status": "Found technical context.",
        "plan": state["plan"] + ["Context Retrieved"],
    }