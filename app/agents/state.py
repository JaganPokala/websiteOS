# --- Imports ---
import operator
from typing import Annotated, List, TypedDict


class AgentState(TypedDict):
    # Using Annotated with operator.add ensures that messages 
    # are appended to the history rather than replaced.
    messages: Annotated[List[dict], operator.add]
    # ai , human , tool , system message 
    current_query: str
    # Full retrieval records, not bare text: each dict carries
    # content / url / title / site / heading / score, so the responder can cite
    # a chunk and main.py can surface its source link.
    documents: List[dict]
    plan: List[str]
    status: str
    final_answer: str
    sites: List[str] 
