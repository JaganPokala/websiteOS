# --- Imports: standard library ---
import asyncio

# --- Imports: third-party ---
import logfire
from qdrant_client import AsyncQdrantClient

# --- Imports: local application ---
from app.config import settings
from app.services.retrieval.embedding import embed_query


# --- Client setup ---
# Async client: query_points becomes awaitable, so the event loop can serve
# other requests while Qdrant Cloud runs the search.
client = AsyncQdrantClient(
    url=settings.QDRANT_URL,
    api_key=settings.QDRANT_API_KEY
)


async def search_enterprise_knowledge(query: str, limit: int = 8):
    """
    Performs a high-precision search in the enterprise knowledge base.
    Uses the modern query_points interface.
    """
    try:
        # embed_query is a blocking OpenAI API call (sync SDK). Offloading it to a
        # helper thread via to_thread keeps the event loop free to serve other
        # requests while the embedding request is in flight.
        query_vector = await asyncio.to_thread(embed_query, query)

        # Using query_points - the modern standard for Qdrant
        response = await client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_vector,
            limit=limit,
            with_payload=True # JSON
        )

        results = []
        for res in response.points:
            results.append({
                "content": res.payload.get("text", ""),
                "source": res.payload.get("source", "Unknown"),
                "score": res.score
            })

        return results
    except Exception as e:
        logfire.error(f"❌ Qdrant Search Failed: {e}")
        return []
