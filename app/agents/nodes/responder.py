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
        max_context_chars = 10000
        full_context = ""
        for doc in state["documents"]:
            if len(full_context) + len(doc) < max_context_chars:
                full_context += doc + "\n\n"
            else:
                logfire.warning("Context truncated to fit the model's token limit.")
                break

        prompt = f"""
        You are a Senior Technical Architect.
        Answer the question using the TECHNICAL CONTEXT provided, in short and simple manner.

        
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
