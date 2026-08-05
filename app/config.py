# --- Imports ---
import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Settings:
    # --- AUTH ---
    # Signs JWT access tokens. Leaking this lets anyone forge a login — keep it in .env only.
    JWT_SECRET = os.getenv("JWT_SECRET")
    
    # --- GEMINI EMBEDDINGS ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    # Embedding backend: "auto" (probe Gemini, fall back to local),
    # "local" (force sentence-transformers), or "gemini" (force Gemini).
    EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "auto").lower()


    # --- VECTOR DB (QDRANT) ---
    QDRANT_URL = os.getenv("QDRANT_CLUSTER_ENDPOINT")
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    QDRANT_COLLECTION = "enterprise_rag"

    # --- RERANKING (FLASHRANK) ---
    # Reranking is the intended behaviour: Qdrant returns 15 candidates, FlashRank
    # scores all of them against the query, and the top 5 go to the responder.
    # Defaults to ON so a forgotten env var can't silently degrade answer quality —
    # on an undersized host this fails loudly (FlashRank's ONNX model loads into
    # process memory on first rerank) instead of quietly serving raw vector order.
    # Set RERANK_ENABLED=false to fall back to raw Qdrant order — the deliberate
    # graceful-degradation lever, not the default.
    RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"

    # --- CONVERSATION MEMORY (POSTGRES CHECKPOINTER) ---
    # Connection string, e.g. postgresql://user:pass@host/dbname
    # Neon: dashboard → Connect → copy the string WITHOUT "-pooler" in the host
    POSTGRES_URI = os.getenv("POSTGRES_URI")

    # --- RATE LIMITING (REDIS) ---
    REDIS_URL = os.getenv("REDIS_URL")
    # Bump this in .env when running the eval suite (many /query calls in a
    # short window) — leave it at the default for real traffic.
    RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "5"))

    # --- CORS ---
    # Comma-separated list of origins allowed to call this API. Defaults to the
    # local Vite dev server so nothing breaks locally; set this env var on the
    # host to your deployed frontend's real origin(s) once you know them.
    FRONTEND_ORIGINS = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

    # --- GROQ (FALLBACK PROVIDER) ---
    # Groq is no longer primary — it's the cross-provider fallback. The fallback
    # model + routing live in the Portkey dashboard config (the @rag target);
    # these just hold the credentials. The eval judge also uses Groq directly.
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_FALLBACK_API_KEY = os.getenv("GROQ_FALLBACK_API_KEY")

    # --- LLM GATEWAY (PORTKEY) ---
    # Saved dashboard config: OpenAI primary → Groq fallback, plus retry + cache.
    PORTKEY_API_KEY = os.getenv("PORTKEY_API_KEY")
    PORTKEY_CONFIG = os.getenv("PORTKEY_CONFIG")
    GROQ_SLUG = "rag"      # Portkey slug for the Groq fallback target (set in the dashboard config)

    # --- OPENAI (PRIMARY LLM + EMBEDDINGS) ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_SLUG = "openai"                 # Portkey integration slug you created

    # Model IDs per slot — change a model here, nowhere else
    RESPONDER_MODEL  = "gpt-5-mini"        # writes the final answer
    PLANNER_MODEL    = "gpt-4.1-nano"      # intent classification (tiny job)
    GUARDRAILS_MODEL = "gpt-4.1-nano"      # safety / topic gate

    # Fallback models (Groq) live in the Portkey dashboard config, not here.

    # --- EMBEDDINGS (OPENAI) ---
    EMBEDDING_MODEL = "text-embedding-3-small"
    EMBEDDING_DIM   = 1536                 # this model's vector size

    # --- INGESTED SITES ---
    # Served by GET /sites so the frontend never hardcodes these. `id` must match
    # the `site` payload value written at ingestion time — it is what the Qdrant
    # filter matches on, so a typo here means a site the user can select and that
    # silently returns nothing.
    #
    # Hardcoded deliberately: the alternative is querying Qdrant for distinct
    # `site` values, which has no cheap primitive (facet/scroll over 1,800+
    # points per request) and still could not supply the display label or
    # description. This list changes once per ingested site.
    AVAILABLE_SITES = [
        {
            "id": "kubernetes.io",
            "label": "Kubernetes",
            "description": "Jobs, CronJobs, autoscaling and workload management",
        },
        {
            "id": "cp-algorithms.com",
            "label": "cp-algorithms",
            "description": "Competitive programming algorithms and data structures",
        },
    ]
    
    # --- OBSERVABILITY ---
    # LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "true")
    # LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
    # LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "rag_scale_test")
    # LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

# # Apply LangChain environment variables for automatic tracing
# os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGSMITH_TRACING", "true")
# os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY", "")
# os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "rag_scale_test")
# os.environ["LANGCHAIN_ENDPOINT"] = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

settings = Settings()
