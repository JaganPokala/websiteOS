# --- Imports: standard library ---
import logging

# --- Imports: third-party ---
import logfire
from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import GenerationLogOptions, GenerationOptions

# --- Imports: local application ---
from app.config import settings
from app.gateway import get_langchain_llm
from app.guardrails.colang_rules import COLANG_CONTENT, RAIL_BOT_INTENTS, YAML_CONTENT

# Ask NeMo for the colang history alongside the response — that structured trace
# is what tells us WHICH canonical form fired, instead of guessing from prose.
_GEN_OPTIONS = GenerationOptions(log=GenerationLogOptions(colang_history=True))

_rails: LLMRails | None = None


def initialize_rails() -> None:
    """
    Build the NeMo LLMRails singleton at app startup.
    Uses gpt-4.1-nano via Portkey for fast intent classification at the gate.
    """
    global _rails

    guard_llm = get_langchain_llm(
        model=f"@{settings.OPENAI_SLUG}/{settings.GUARDRAILS_MODEL}",
        feature="guardrails",
    )


     
    config = RailsConfig.from_content(
        colang_content=COLANG_CONTENT,
        yaml_content=YAML_CONTENT
    )

    _rails = LLMRails(config, llm=guard_llm)
    logfire.info("🛡️ NeMo Guardrails initialised (gpt-4.1-nano via Portkey).")

    # NeMo logs every internal colang event at INFO — extremely noisy.
    # Quiet it (and httpx's per-request lines) down to warnings only.
    logging.getLogger("nemoguardrails").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def guard(message: str) -> tuple[bool, str | None]:
    """
    Run a user message through the NeMo rails gate.

    Returns:
        (True,  rail_response) — a rail fired; return this response immediately,
                                skip the RAG pipeline entirely.
        (False, None)          — message is clean; proceed to LangGraph.
    """
    if _rails is None:
        logfire.warning("⚠️ Guardrails not initialised — skipping gate.")
        return False, None

    with logfire.span("🛡️ Guardrails Check"):
        result = await _rails.generate_async(
            messages=[{"role": "user", "content": message}],
            options=_GEN_OPTIONS,
        )

        # With `options`, NeMo returns a GenerationResponse (.response is a list
        # of messages) rather than the bare dict it returns without them.
        response = getattr(result, "response", result)
        if isinstance(response, list):
            response = response[0] if response else {}
        content = response.get("content", "") if isinstance(response, dict) else str(response)

        # Decide from the STRUCTURED trace, not the prose. colang_history looks like:
        #     user "ignore all previous instructions"
        #       attempt jailbreak
        #     bot refuse jailbreak
        #       "I can't comply with that request — ..."
        # so the canonical form is exact and survives any rewording of the message.
        # A clean question yields `bot general response`, which is not a defined
        # rail and therefore never matches.
        history = getattr(getattr(result, "log", None), "colang_history", "") or ""
        fired_intent = next(
            (intent for intent in RAIL_BOT_INTENTS if f"bot {intent}" in history),
            None,
        )

        if fired_intent:
            logfire.info(
                "🛡️ Guardrails fired",
                intent=fired_intent,
                query=message[:80],
            )
            return True, content

        logfire.info("✅ Guardrails passed.")
        return False, None
