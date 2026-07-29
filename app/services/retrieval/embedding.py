# --- Imports: third-party ---
import logfire
from openai import OpenAI

# --- Imports: local application ---
from app.config import settings

# --- Config ---
# OpenAI accepts large batches; 100 chunks per request stays well within limits.
BATCH_SIZE = 100

_client: OpenAI | None = None


# --- Client setup ---
def _get_client() -> OpenAI:
    """Create the OpenAI client once, on first use."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logfire.info(
            f"OpenAI embeddings ready ({settings.EMBEDDING_MODEL}, {settings.EMBEDDING_DIM}-dim)."
        )
    return _client


# --- Public API ---
def get_embedding_dim() -> int:
    """Vector size of the embedding model — used to size the Qdrant collection."""
    return settings.EMBEDDING_DIM


def embed_query(query: str) -> list[float]:
    """Embed a single query string → one vector."""
    client = _get_client()
    resp = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=query)
    return resp.data[0].embedding


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed many chunks in batches. Order is preserved to match the input list."""
    client = _get_client()
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        with logfire.span("Embed batch", model=settings.EMBEDDING_MODEL, start=i, size=len(batch)):
            resp = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=batch)
            # Sort by index so vectors line up with input order, regardless of API ordering.
            ordered = sorted(resp.data, key=lambda d: d.index)
            all_embeddings.extend(d.embedding for d in ordered)
    return all_embeddings