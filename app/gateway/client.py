# --- Imports: third-party ---
import logfire
from langchain_openai import ChatOpenAI
from portkey_ai import AsyncPortkey, PORTKEY_GATEWAY_URL, createHeaders

# --- Imports: local application ---
from app.config import settings


# --- Client setup ---
# Async client: .create() becomes awaitable, so the responder parks its task on
# the event loop instead of freezing it while the model generates.
portkey_client = AsyncPortkey(
    api_key=settings.PORTKEY_API_KEY,
    config=settings.PORTKEY_CONFIG
)


def get_langchain_llm(
        model: str,
        feature: str = "rag", 
        temperature: float | None = 0,
        reasoning_effort: str | None = None,
        ) -> ChatOpenAI:
    """
    Returns a Portkey-backed ChatOpenAI for LangChain nodes.
    `model` is a full Portkey model string, e.g. "@openai/gpt-4.1-nano".
    The saved Portkey config (PORTKEY_CONFIG) adds fallback + retry + cache;
    its pass-through primary forwards whatever model we pass here.

    `temperature` defaults to 0 (deterministic — right for classification jobs
    like the planner and guardrails). Pass temperature=None for reasoning-tier
    models (e.g. gpt-5-mini) that reject any explicit value but the default;
    None omits the kwarg entirely instead of sending an unsupported one.
    """
    kwargs = {} if temperature is None else {"temperature": temperature}
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    return ChatOpenAI(
        api_key=settings.PORTKEY_API_KEY,
        base_url=PORTKEY_GATEWAY_URL,
        model=model,
        default_headers=createHeaders(
            api_key=settings.PORTKEY_API_KEY,
            config=settings.PORTKEY_CONFIG,
            metadata={
                "feature": feature,
                "_user": "rag-system",
                "environment": "production"
            }
        ),
        **kwargs,
    )


def extract_cache_status(response) -> str:
    """
    Pull x-portkey-cache-status from the Portkey native client response headers.
    Tries multiple attribute paths defensively — returns 'MISS' if not found.
    """
    for attr in ("_raw_response", "_response", "_http_response"):
        raw = getattr(response, attr, None)
        if raw is not None:
            status = getattr(raw, "headers", {}).get("x-portkey-cache-status", "")
            if status:
                return status.upper()
    return "MISS"