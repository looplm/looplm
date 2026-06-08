"""Base declarative class and shared enums for LoopLM models."""

import enum

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ── Enums ──────────────────────────────────────────────────────

class IntegrationType(str, enum.Enum):
    langfuse = "langfuse"
    langsmith = "langsmith"
    json_file = "json_file"
    looplm = "looplm"  # first-party push-based tracing (SDK → ingest endpoint)


class IndexProviderType(str, enum.Enum):
    """Retrieval-index backends looplm can read a corpus from for coverage.

    Only ``azure_search`` is implemented today; the others are reserved so the
    enum/migration are stable as backends are added (each needs a
    BaseIndexProvider subclass + a branch in the registry factory).
    """

    azure_search = "azure_search"
    pinecone = "pinecone"
    qdrant = "qdrant"
    pgvector = "pgvector"


class SyncStatus(str, enum.Enum):
    idle = "idle"
    syncing = "syncing"
    error = "error"
    never = "never"


class TraceStatus(str, enum.Enum):
    success = "success"
    failure = "failure"
    degraded = "degraded"


class SpanType(str, enum.Enum):
    llm = "llm"
    tool = "tool"
    retriever = "retriever"
    chain = "chain"
    agent = "agent"


class FixType(str, enum.Enum):
    prompt_rewrite = "prompt_rewrite"
    tool_config = "tool_config"
    knowledge_gap = "knowledge_gap"
    parameter_change = "parameter_change"


class FixStatus(str, enum.Enum):
    pending = "pending"
    applied = "applied"
    dismissed = "dismissed"


class CodeSuggestionType(str, enum.Enum):
    prompt_change = "prompt_change"
    code_fix = "code_fix"
    config_change = "config_change"
    architecture_change = "architecture_change"


class CodeSuggestionStatus(str, enum.Enum):
    pending = "pending"
    applied = "applied"
    dismissed = "dismissed"


class SignalType(str, enum.Enum):
    """Kinds of production signal that can feed issue detection."""

    explicit_failure = "explicit_failure"   # trace status == failure / error span
    eval_failure = "eval_failure"           # auto-grade / online evaluator failed
    negative_feedback = "negative_feedback"  # low user feedback score
    anomaly = "anomaly"                     # latency / token / step-count outlier
    # Behavioral signals classified by an LLM over the trace's input/output.
    refusal = "refusal"                     # assistant declined / refused the request
    user_frustration = "user_frustration"   # user re-asked or expressed dissatisfaction
    task_incomplete = "task_incomplete"     # agent stopped without completing the request
    loop = "loop"                           # agent repeated the same step / got stuck


# Behavioral signal types — the subset classified by the LLM signal classifier
# (the others are derived from status / evals / feedback / latency by rules).
BEHAVIORAL_SIGNAL_TYPES = (
    SignalType.refusal,
    SignalType.user_frustration,
    SignalType.task_incomplete,
    SignalType.loop,
)


class IssueSeverity(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class IssueStatus(str, enum.Enum):
    open = "open"
    diagnosing = "diagnosing"
    resolving = "resolving"
    resolved = "resolved"
    recurring = "recurring"   # was resolved, then the pattern came back
    dismissed = "dismissed"
