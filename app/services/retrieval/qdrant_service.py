# --- Imports: standard library ---
import asyncio

# --- Imports: third-party ---
import logfire
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

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


async def search_enterprise_knowledge(
    query: str,
    limit: int = 8,
    sites: list[str] | None = None,
):
    """
    Performs a high-precision search in the enterprise knowledge base.

    `sites` restricts the search to those site values (e.g. ["cp-algorithms.com"]).
    None or empty searches everything — the existing behaviour, unchanged.
    """
    try:
        query_vector = await asyncio.to_thread(embed_query, query)

        # STEP 1: build the filter.
        #   - if `sites` is falsy -> query_filter stays None (search everything)
        #   - else -> models.Filter(must=[models.FieldCondition(
        #                 key="site", match=models.MatchAny(any=sites))])
        #
        #   MatchAny is OR across the list: site == "a" OR site == "b".
        #   This is why ensure_collection() creates the payload index on "site" —
        #   without it Qdrant scans every point instead of using the index.
        query_filter = None
        if sites:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="site",
                        match=models.MatchAny(any=sites),
                    )
                ]
            )

        # STEP 2: pass it to query_points as `query_filter=...`
        #         (passing None is fine — that's the unfiltered case)
        response = await client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

        # STEP 3: carry the new payload fields out.
        #         Existing keys stay exactly as they are — the retriever reads
        #         doc['content'] today and must keep working.
        #         Add: url, title, site   (and heading if you want it for display)
        #         Use .get() with sensible defaults — old points from a previous
        #         ingestion wouldn't have these keys.
        results = []
        for res in response.points:
            # with_payload=True is set above, but a point ingested without a
            # payload still comes back as None — {} keeps .get() from blowing up.
            payload = res.payload or {}
            results.append({
                "content": payload.get("text", ""),
                "source": payload.get("source", "Unknown"),
                "score": res.score,
                # STEP 3a: url, title, site here
                "url": payload.get("url", ""),
                "title": payload.get("title", ""),
                "site": payload.get("site", ""),
                # this chunk's own heading — the citation anchor the ingestion
                # pipeline writes per chunk. "" on points from an older run.
                "heading": payload.get("heading", ""),
            })

        # A wrong site name returns 0 results with no error — indistinguishable
        # from "nothing relevant found" unless the filter itself is recorded.
        # Same silent-empty failure the log in fetch_sitemap_urls exists to catch.
        logfire.info(
            "🔍 Qdrant search",
            sites=sites or "all",
            limit=limit,
            results=len(results),
        )

        return results
    except Exception as e:
        logfire.error(f"❌ Qdrant Search Failed: {e}")
        return []
