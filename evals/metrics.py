"""
Phase 2 — RAGAS + Tool Correctness metrics.
Judge is gpt-4.1-nano via OpenAI directly (OPENAI_API_KEY) — same key the rest
of the app already uses for planner/guardrails. OpenAI's rate limits are high
enough that all samples run in a single batch per experiment, no cooldowns
needed (unlike the old Groq judge, whose free-tier 6,000 TPM ceiling forced
one-sample-at-a-time pacing with 40-62s waits between batches).
Contexts are still truncated to 300 chars (2 chunks max) to keep each judge
call small and cheap — not for rate-limit reasons anymore, just cost/speed.
"""


import sys
import types
import logfire
import pandas as pd
from openai import AsyncOpenAI

# ragas==0.4.3's ragas/llms/base.py imports ChatVertexAI from
# langchain_community.chat_models.vertexai, a path langchain_community removed
# in 0.4.x (VertexAI support moved to the standalone langchain_google_vertexai
# package). No ragas release fixes this yet (upstream: ragas issue #2745), so
# we shim the old module path before ragas is imported anywhere.
if "langchain_community.chat_models.vertexai" not in sys.modules:
    try:
        import langchain_community.chat_models.vertexai  # noqa: F401
    except ModuleNotFoundError:
        from langchain_google_vertexai import ChatVertexAI

        _vertexai_shim = types.ModuleType("langchain_community.chat_models.vertexai")
        _vertexai_shim.ChatVertexAI = ChatVertexAI
        sys.modules["langchain_community.chat_models.vertexai"] = _vertexai_shim

from ragas.llms import llm_factory
from ragas.embeddings import OpenAIEmbeddings
from ragas import SingleTurnSample
from app.config import settings
from ragas.metrics.collections import (
    Faithfulness,
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    AnswerCorrectness,
)

JUDGE_MODEL = "gpt-4.1-nano"
GENERAL_BATCH_SIZE = 20  # comfortably above the 15-sample dataset — always one real batch
CONTEXT_TRUNCATE = 300   # chars per context chunk — keeps each judge call small and cheap
CONTEXT_LIMIT = 2        # number of context chunks passed to RAGAS per sample


def _build_judge():
    # One client for both: the judge LLM and the embeddings model are both
    # OpenAI now, unlike the old Groq judge which needed a second client just
    # to reach OpenAI for embeddings (Groq doesn't serve embedding models).
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    # max_tokens: ragas defaults to 1024, which truncates Faithfulness's structured
    # output — it emits one NLI verdict per extracted statement, so a multi-statement
    # answer overruns the cap and instructor raises IncompleteOutputException mid-run.
    # ragas' own docs recommend 4096+ for exactly this failure.
    llm = llm_factory(JUDGE_MODEL, provider="openai", client=client, max_tokens=4096)

    # Same embedding model the live RAG pipeline uses to embed queries
    # (app/services/retrieval/embedding.py) — not an unrelated local model.
    # Scores from AnswerRelevancy/AnswerCorrectness measure similarity in the
    # SAME vector space retrieval actually runs in, not a different one.
    embeddings = OpenAIEmbeddings(client=client, model=settings.EMBEDDING_MODEL)
    return llm, embeddings


def _prep_samples(golden_dataset: dict) -> list:
    """
    Returns only samples with actual_response populated.
    Truncates contexts to CONTEXT_TRUNCATE chars and limits to CONTEXT_LIMIT chunks
    so a single RAGAS LLM call stays well under the 6,000 TPM ceiling.
    (Live contexts from Qdrant are ~1,500 chars each — without truncation a single
    Faithfulness request exceeds 7,000 tokens which hard-fails on the on_demand tier.)
    """
    valid = []
    for s in golden_dataset["rag_samples"]:
        response = s.get("actual_response", "").strip()
        if not response:
            continue
        raw_contexts = s.get("actual_contexts") or s.get("relevant_contexts") or []
        contexts = [c[:CONTEXT_TRUNCATE] for c in raw_contexts[:CONTEXT_LIMIT]]
        valid.append({**s, "actual_contexts": contexts})
    return valid


def _score_df(metric_key: str, samples: list, scores) -> pd.DataFrame:
    return pd.DataFrame([
        {"question": s["question"][:65], metric_key: round(float(r.value), 3)}
        for s, r in zip(samples, scores)
    ])


async def _batched_score(metric, inputs: list, samples: list, status_cb=None, label: str = "") -> list:
    """
    Runs abatch_score in chunks of GENERAL_BATCH_SIZE. With OpenAI's rate limits,
    GENERAL_BATCH_SIZE is set above the dataset size, so this is always one batch —
    the chunking loop stays only so a bigger dataset degrades gracefully instead
    of firing an unbounded burst of concurrent calls.
    """
    all_scores = []
    batches = [inputs[i : i + GENERAL_BATCH_SIZE] for i in range(0, len(inputs), GENERAL_BATCH_SIZE)]
    for batch in batches:
        scores = await metric.abatch_score(batch)
        all_scores.extend(scores)
    return all_scores

async def run_all_metrics(golden_dataset: dict, status_cb=None) -> dict:
    """
    Runs all 6 experiments. Returns dict keyed by metric name → DataFrame.
    status_cb(message: str) is called for live UI updates.
    """
    judge_llm, ragas_embeddings = _build_judge()
    samples = _prep_samples(golden_dataset)

    if not samples:
        raise ValueError("No samples with actual_response found. Run Phase 1 first.")

    results = {}

    with logfire.span("🧪 Eval Phase 2 — All Metrics", total_samples=len(samples)):

        # ── Exp 1: Faithfulness ───────────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 1/6 — Faithfulness ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 1 — Faithfulness"):
            inputs = [
                {
                    "user_input": s["question"],
                    "response": s["actual_response"],
                    "retrieved_contexts": s["actual_contexts"],
                }
                for s in samples
            ]
            scores = await _batched_score(Faithfulness(llm=judge_llm), inputs, samples, status_cb, "Faithfulness")
            df = _score_df("faithfulness", samples, scores)
            results["faithfulness"] = df
            logfire.info("🧪 Faithfulness done", avg=round(df["faithfulness"].mean(), 3))

        # ── Exp 2: Answer Relevancy ───────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 2/6 — Answer Relevancy ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 2 — Answer Relevancy"):
            inputs = [
                {"user_input": s["question"], "response": s["actual_response"]}
                for s in samples
            ]
            scores = await _batched_score(
                AnswerRelevancy(llm=judge_llm, embeddings=ragas_embeddings),
                inputs, samples, status_cb, "Answer Relevancy"
            )
            df = _score_df("answer_relevancy", samples, scores)
            results["answer_relevancy"] = df
            logfire.info("🧪 Answer Relevancy done", avg=round(df["answer_relevancy"].mean(), 3))

        # ── Exp 3: Context Precision ──────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 3/6 — Context Precision ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 3 — Context Precision"):
            inputs = [
                {
                    "user_input": s["question"],
                    "reference": s["reference"],
                    "retrieved_contexts": s["actual_contexts"],
                }
                for s in samples
            ]
            scores = await _batched_score(ContextPrecision(llm=judge_llm), inputs, samples, status_cb, "Context Precision")
            df = _score_df("context_precision", samples, scores)
            results["context_precision"] = df
            logfire.info("🧪 Context Precision done", avg=round(df["context_precision"].mean(), 3))

        # ── Exp 4: Context Recall ─────────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 4/6 — Context Recall ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 4 — Context Recall"):
            inputs = [
                {
                    "user_input": s["question"],
                    "reference": s["reference"],
                    "retrieved_contexts": s["actual_contexts"],
                }
                for s in samples
            ]
            scores = await _batched_score(ContextRecall(llm=judge_llm), inputs, samples, status_cb, "Context Recall")
            df = _score_df("context_recall", samples, scores)
            results["context_recall"] = df
            logfire.info("🧪 Context Recall done", avg=round(df["context_recall"].mean(), 3))

        # ── Exp 5: Answer Correctness (split into batches) ────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 5/6 — Answer Correctness batch 1/2...")
        with logfire.span("🧪 Exp 5 — Answer Correctness"):
            inputs = [
                {
                    "user_input": s["question"],
                    "response": s["actual_response"],
                    "reference": s["reference"],
                }
                for s in samples
            ]
            all_scores = await _batched_score(
                AnswerCorrectness(llm=judge_llm, embeddings=ragas_embeddings),
                inputs, samples, status_cb, "Answer Correctness"
            )
            df = _score_df("answer_correctness", samples, all_scores)
            results["answer_correctness"] = df
            logfire.info("🧪 Answer Correctness done", avg=round(df["answer_correctness"].mean(), 3))

        # ── Exp 6: Tool Correctness (no LLM — Jaccard) ───────────────────────
        if status_cb:
            status_cb("⚡ Exp 6/6 — Tool Correctness (zero LLM calls)...")
        with logfire.span("🧪 Exp 6 — Tool Correctness"):
            tool_rows = []
            for s in samples:
                called = set(s.get("actual_tools_called") or [])
                expected = set(s.get("expected_tools") or [])
                union = len(called | expected)
                score = len(called & expected) / union if union > 0 else 0.0
                tool_rows.append({"question": s["question"][:65], "tool_correctness": round(score, 3)})
            df = pd.DataFrame(tool_rows)
            results["tool_correctness"] = df
            logfire.info("🧪 Tool Correctness done", avg=round(df["tool_correctness"].mean(), 3))

        if status_cb:
            status_cb("✅ All 6 experiments complete!")

    return results
