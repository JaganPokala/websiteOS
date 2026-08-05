# --- Imports: standard library ---
import time

# --- Imports: third-party ---
import logfire
from flashrank import Ranker, RerankRequest

# Lazy initialization - Ranker is loaded on first use to ensure logfire.configure() has run
_ranker = None


# --- Client setup ---
def _get_ranker() -> Ranker:
    """
    Initializes the FlashRank engine lazily. 
    FlashRank uses a local ONNX model (ms-marco-MiniLM-L-6-v2) for ultra-fast reranking.
    """
    global _ranker
    if _ranker is None:
        logfire.info("🧠 Initializing FlashRank Model (TinyBERT) locally...")
        try:
            # We use a specific cache directory to avoid permission issues in production
            _ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
        except Exception:
            _ranker = Ranker()
    return _ranker


# --- Public API ---
def rerank_documents(query: str, documents: list[str], top_n: int = 5) -> list[int]:
    """
    Re-scores documents against the query with a cross-encoder and returns the
    INDICES of the best ones, highest score first.

    Returns positions, not text, so the caller can map each result back to the
    full record it came from (url, title, site). Returning text loses that link:
    two chunks with identical content are indistinguishable, and matching them
    back by string would attach the wrong citation URL to an answer — a wrong
    link that looks perfectly valid.
    """
    # STEP 1: empty input -> return [] (unchanged)
    if not documents:
        return []

    start_time = time.time()
    logfire.info(f"📡 [Reranker] Sending {len(documents)} docs to FlashRank Cross-Encoder...")

    try:
        ranker = _get_ranker()

        # STEP 2: build passages exactly as now — {"id": i, "text": doc}.
        #         The id is already the index; today line 60 throws it away by
        #         returning only res['text']. That is the whole bug this fixes.
        passages = [
            {"id": i, "text": doc}
            for i, doc in enumerate(documents)
        ]

        # STEP 3: run the reranker, take results[:top_n]
        request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(request)

        # STEP 4: return [res["id"] for res in results[:top_n]]
        #         FlashRank returns them sorted by score descending, so the order of
        #         this list IS the ranking — the caller must preserve it.
        top_ids = [res["id"] for res in results[:top_n]]

        # STEP 5: keep the logging as-is (duration + top score).
        duration = time.time() - start_time
        top_score = results[0]['score'] if results else 'N/A'
        logfire.info(f"✅ [Reranker] Done in {duration:.2f}s. Top semantic score: {top_score}")

        return top_ids

    except Exception as e:
        logfire.error(f"❌ [Reranker] Semantic Reranking Failed: {e}")
        # STEP 6: the except branch currently returns documents[:top_n].
        #         It must now return INDICES for that same slice, so the caller's
        #         mapping works identically on the fallback path.
        #         Fallback to the original Qdrant order to ensure the user still
        #         gets an answer.
        return list(range(min(top_n, len(documents))))