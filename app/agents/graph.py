# --- Imports: third-party ---
from langgraph.graph import END, StateGraph

# --- Imports: local application ---
from app.agents.nodes.planner import planner_node
from app.agents.nodes.responder import generate_node
from app.agents.nodes.retriever import retrieve_node
from app.agents.state import AgentState


# 1. Initialize the State Graph
workflow = StateGraph(AgentState)


# 2. Define the Nodes
workflow.add_node("planner", planner_node)
workflow.add_node("retriever", retrieve_node)
workflow.add_node("responder", generate_node)

# 3. Define the Edges & Routing Logic
def route_planner(state: AgentState):
    """
    Routes the workflow based on the planner's decision.
    """
    if state["current_query"] == "CONVERSATIONAL":
        return "responder"
    return "retriever"

workflow.set_entry_point("planner")


# Conditional Edge: Planner -> Router -> (Retriever OR Responder)
workflow.add_conditional_edges(
    "planner",
    route_planner,
    {
        "retriever": "retriever",
        "responder": "responder"
    }
)


workflow.add_edge("retriever", "responder")
workflow.add_edge("responder", END)


# --- MEMORY UPGRADE ---
# The checkpointer (AsyncPostgresSaver) is injected at startup by main.py's
# lifespan. Conversation snapshots live in Postgres — outside this process —
# so they survive restarts and can be shared by multiple worker processes.
rag_agent = None


def compile_graph(checkpointer):
    """Compile the graph with a checkpointer. Called once at app startup."""
    global rag_agent
    rag_agent = workflow.compile(checkpointer=checkpointer)
    return rag_agent


