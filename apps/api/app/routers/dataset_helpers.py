"""Pure helper functions for dataset endpoints.

This module is a thin re-export facade. The implementations live in two
focused submodules:

- :mod:`app.routers.dataset_conversation` — conversation extraction,
  greeting stripping, and LLM summarization helpers.
- :mod:`app.routers.dataset_suggestions` — retrieval-source extraction and
  test-case suggestion building/enrichment.

Importers historically pull these symbols from ``app.routers.dataset_helpers``,
so every public (and underscore-prefixed but externally-used) name is
re-exported here to keep those imports working. ``extract_retrieval_source_urls``
is itself re-exported from ``app.services.retrieval_config`` because
``analytics.py`` imports it from here.
"""

from __future__ import annotations

from app.services.retrieval_config import extract_retrieval_source_urls

from .dataset_conversation import (
    _GREETING_WITH_PREFIX,
    _extract_conversation_history,
    _extract_user_prompt,
    _tc_to_item,
    build_contextualized_prompt,
    load_trace_conversation_messages,
    strip_personal_greeting,
    summarize_conversation,
)
from .dataset_suggestions import (
    _extract_answer,
    _source_label,
    build_suggestions,
    enrich_suggestions_with_llm,
    extract_retrieval_sources,
    generate_expected_answer,
    load_trace_source_urls,
    score_dataset_relevance,
)

__all__ = [
    "_GREETING_WITH_PREFIX",
    "_extract_answer",
    "_extract_conversation_history",
    "_extract_user_prompt",
    "_source_label",
    "_tc_to_item",
    "build_contextualized_prompt",
    "build_suggestions",
    "enrich_suggestions_with_llm",
    "extract_retrieval_source_urls",
    "extract_retrieval_sources",
    "generate_expected_answer",
    "load_trace_conversation_messages",
    "load_trace_source_urls",
    "score_dataset_relevance",
    "strip_personal_greeting",
    "summarize_conversation",
]
