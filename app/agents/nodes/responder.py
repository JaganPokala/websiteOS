# --- Imports: third-party ---
import logfire

# --- Imports: local application ---
from app.agents.state import AgentState
from app.config import settings
from app.gateway import get_langchain_llm

# Portkey-backed LLM (gpt-5-mini). Using the LangChain client (not the native
# Portkey one) lets LangGraph stream this node's tokens to the client via
# astream(stream_mode="messages"). Trade-off: we lose the cache-hit header,
# but Portkey's dashboard still logs every HIT/MISS.
# temperature=None: gpt-5-mini is reasoning-tier and rejects any explicit
# temperature (including the client's default of 0) with a 400 — only the
# model's own default (1) is accepted, so we omit the parameter entirely.
llm = get_langchain_llm(
    model=f"@{settings.OPENAI_SLUG}/{settings.RESPONDER_MODEL}",
    feature="responder",
    temperature=None,
    reasoning_effort="medium",
)


async def generate_node(state: AgentState):
    """
    Synthesizes the answer from Documentation Context AND Conversation History.
    Streams tokens (llm.astream) so the endpoint can push them to the client;
    also accumulates the full answer so the checkpointer can save it.
    """
    query = state["current_query"]

    history_str = ""
    for msg in state["messages"][:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        history_str += f"{role}: {msg['content']}\n"

    user_msg = state["messages"][-1]["content"] if state["messages"] else ""

    if query == "CONVERSATIONAL":
        logfire.info("Generating conversational response using memory.")
        prompt = f"""
        You are a friendly and helpful Enterprise AI Assistant.
        Answer the user's latest message using the CONVERSATION HISTORY below.

        CONVERSATION HISTORY:
        {history_str}

        LATEST MESSAGE:
        "{user_msg}"
        """
    else:
        logfire.info("Generating technical RAG response.")
        max_context_chars = 15000
        full_context = ""

        # STEP 1: state["documents"] is now a list of dicts, so iterate with an
        #         index — enumerate(state["documents"], start=1) — and read the
        #         text with doc["content"].
        #
        #         The bug being fixed: `len(doc)` on a dict returns the NUMBER OF
        #         KEYS (7), not the text length. It doesn't raise — the budget
        #         check just silently compares against 7 every time, and
        #         `full_context += doc` stringifies the whole dict into the prompt.
        for i, doc in enumerate(state["documents"], start=1):
            # STEP 2: build one block per document. Number it so the model can refer
            #         to a specific source.
            #
            #         No title or heading here — the chunker already prefixed every
            #         chunk's text with its breadcrumb ("Binary Exponentiation >
            #         Algorithm\n\n..."), so provenance is already inside
            #         doc["content"]. Adding it again would duplicate it.
            block = f"[{i}]\n{doc['content']}\n\n"

            # STEP 3: keep the truncation guard, but measure the BLOCK you are
            #         about to add, not the raw doc.
            if len(full_context) + len(block) < max_context_chars:
                full_context += block
            else:
                logfire.warning(
                    "Context budget reached — dropping the lowest-ranked documents.",
                    kept=i - 1,
                    total=len(state["documents"]),
                    chars=len(full_context),
                )
                break

        prompt = f"""
        You are a Senior Technical Architect.
        Answer the question using the TECHNICAL CONTEXT provided, in short and simple manner.

        Each block in the TECHNICAL CONTEXT starts with a number in brackets, like [1].
        When a statement comes from a block, cite that block inline right after the
        statement, e.g. "CronJobs use cron syntax [2]." Cite only numbers that actually
        appear below — never invent a source. If the context does not answer the
        question, say so plainly instead of guessing.

        TECHNICAL CONTEXT:
        {full_context}

        CONVERSATION HISTORY:
        {history_str}

        USER QUESTION:
        "{user_msg}"
        """

    with logfire.span("✍️ LLM Synthesis"):
        # Stream tokens as they generate, and accumulate the full answer.
        content = ""
        async for chunk in llm.astream(prompt):
            content += chunk.content or ""
        logfire.info("✅ Response synthesised via LLM.")

    return {
        "final_answer": content,
        "status": "Response generated.",
        "plan": state["plan"],
        "messages": [{"role": "assistant", "content": content}],
    }