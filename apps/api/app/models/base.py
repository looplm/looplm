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
