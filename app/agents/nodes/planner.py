# --- Imports: standard library ---
import re

# --- Imports: third-party ---
import logfire

# --- Imports: local application ---
from app.agents.state import AgentState
from app.config import settings
from app.gateway import get_langchain_llm

# Portkey-backed LLM (gpt-4.1-nano): OpenAI primary + Groq fallback + cache + retry, via the gateway.
llm = get_langchain_llm(
    model=f"@{settings.OPENAI_SLUG}/{settings.PLANNER_MODEL}",
    feature="planner",
)


def _indexed_topics() -> str:
    """The searchable domains, derived from the same list GET /sites serves.

    Hardcoding them here is what broke routing once already: the prompt still
    named "Kubernetes, Intel, or Networking" long after Intel was gone and
    cp-algorithms had been ingested, so algorithm questions matched no
    retrievable category and fell through to CONVERSATIONAL — skipping
    retrieval entirely and answering from the model's own memory.
    Deriving it means ingesting a site updates the router for free.
    """
    return "\n".join(
        f"      - {s['label']} ({s['id']}): {s['description']}"
        for s in settings.AVAILABLE_SITES
    )


async def planner_node(state: AgentState):
    """
    The Planner determines if a search is needed based on the ENTIRE conversation.
    """
    # Get the conversation history (excluding the latest message)
    history = ""
    for msg in state["messages"][:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        history += f"{role}: {msg['content']}\n"

    user_message = state["messages"][-1]["content"] if state["messages"] else ""

    prompt = f"""
    You are a routing classifier for a documentation assistant.

    The assistant can search these indexed sources:
{_indexed_topics()}

    CONVERSATION HISTORY:
    {history}

    LATEST MESSAGE:
    "{user_message}"

    Decide how to handle the LATEST MESSAGE.

    Output exactly 'CONVERSATIONAL' ONLY when it needs no documentation at all:
      - a greeting, thanks, or small talk ("hi", "thanks", "bye")
      - a question about the conversation itself ("what did I just ask?", "summarise that")

    Otherwise the user is asking for information — output a short search query
    (3-10 words) describing what to look up.

    Bias towards searching. An unnecessary search costs a little latency; a
    missed one makes the assistant answer from its own memory instead of the
    documentation, which is the failure this system exists to prevent. A topic
    already discussed is NOT a reason to skip: a new question about it still
    needs fresh documentation.

    Resolve shorthand and pronouns against the history — after a graph
    discussion, "and dijkstra?" becomes "dijkstra shortest path algorithm".

    Output ONLY the word CONVERSATIONAL or the bare search query. No preamble,
    no quotes, no "search query:" prefix.
    """

    with logfire.span("🧠 Planner Decision"):
        decision = (await llm.ainvoke(prompt)).content.strip()
        # Small models still echo the instruction wording ("refined search query:
        # \"binary exponentiation\"") despite being told not to. Left in place it
        # gets embedded verbatim and drags the query vector towards the prompt's
        # own phrasing rather than the user's question.
        decision = re.sub(r'^(refined\s+)?search\s+query\s*:\s*', "", decision, flags=re.I)
        decision = decision.strip().strip('"').strip("'").strip()
        logfire.info(f"Intent identified: {decision}")

    if decision == "CONVERSATIONAL":
        return {
            "current_query": "CONVERSATIONAL",
            "status": "Handling conversationally (using memory)...",
            "plan": ["Intent: Conversational/Memory", "Retrieval: Skipped"]
        }
    
    return {
        "current_query": decision,
        "status": f"Technical research needed. Searching for: {decision}",
        "plan": ["Intent: Technical", f"Search Term: {decision}"]
    }
