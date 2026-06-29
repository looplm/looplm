"""LangChain template-extraction and trace normalization helpers for LangSmith.

These are pure, stateless functions extracted from ``LangSmithConnector`` so the
connector module stays small. The connector keeps thin delegating methods that
call into here, preserving the original public method names.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def extract_template(manifest: dict) -> str:
    """Extract prompt template text from a LangSmith commit manifest."""
    # LangChain serialized format: {"lc": 1, "type": "constructor", "id": [...], "kwargs": {...}}
    if "lc" in manifest and "kwargs" in manifest:
        return extract_from_lc(manifest)

    # Direct template string (completion-style prompts)
    template = manifest.get("template", "")
    if template:
        return template if isinstance(template, str) else str(template)

    # Chat-style prompts: list of message objects
    messages = manifest.get("messages")
    if messages and isinstance(messages, list):
        return format_messages(messages)

    return ""


def extract_from_lc(obj: dict) -> str:
    """Recursively extract template text from a LangChain serialized object."""
    kwargs = obj.get("kwargs", {})

    # If this object has a direct template string, return it
    if isinstance(kwargs.get("template"), str) and kwargs["template"]:
        return kwargs["template"]

    # If this object has messages (ChatPromptTemplate), extract from each
    messages = kwargs.get("messages")
    if messages and isinstance(messages, list):
        parts = []
        for msg in messages:
            if isinstance(msg, dict) and "lc" in msg:
                # Nested LangChain object (e.g. SystemMessagePromptTemplate)
                msg_kwargs = msg.get("kwargs", {})
                # The role is derived from the class name
                msg_id = msg.get("id", [])
                role = lc_id_to_role(msg_id)

                # Extract content from the nested prompt
                prompt = msg_kwargs.get("prompt", {})
                if isinstance(prompt, dict) and "kwargs" in prompt:
                    content = prompt["kwargs"].get("template", "")
                else:
                    content = msg_kwargs.get("template", msg_kwargs.get("content", ""))

                if role and content:
                    parts.append(f"[{role}]\n{content}")
                elif content:
                    parts.append(str(content))
            elif isinstance(msg, dict):
                role = msg.get("role", msg.get("type", ""))
                content = msg.get("content", msg.get("text", ""))
                if role and content:
                    parts.append(f"[{role}]\n{content}")
                elif content:
                    parts.append(str(content))
        return "\n\n".join(parts)

    # If this has a nested prompt object
    prompt = kwargs.get("prompt", {})
    if isinstance(prompt, dict) and "kwargs" in prompt:
        return extract_from_lc(prompt)

    return ""


def lc_id_to_role(lc_id: list) -> str:
    """Map a LangChain class ID to a chat role name."""
    if not lc_id:
        return ""
    class_name = lc_id[-1] if lc_id else ""
    mapping = {
        "SystemMessagePromptTemplate": "system",
        "HumanMessagePromptTemplate": "human",
        "AIMessagePromptTemplate": "ai",
        "SystemMessage": "system",
        "HumanMessage": "human",
        "AIMessage": "ai",
    }
    return mapping.get(class_name, class_name)


def format_messages(messages: list) -> str:
    """Format a list of plain message dicts into template text."""
    parts = []
    for m in messages:
        role = m.get("role", m.get("type", ""))
        content = m.get("content", m.get("text", ""))
        if isinstance(content, list):
            content = " ".join(
                c.get("text", str(c)) if isinstance(c, dict) else str(c)
                for c in content
            )
        if role:
            parts.append(f"[{role}]\n{content}")
        else:
            parts.append(str(content))
    return "\n\n".join(parts)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp string into a datetime object."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def extract_thread_id(metadata: dict[str, Any]) -> str | None:
    """Extract thread ID from run metadata, checking common key names."""
    if not metadata:
        return None
    return metadata.get("thread_id") or metadata.get("session_id") or metadata.get("conversation_id")


def map_run_type(run_type: str) -> str:
    mapping = {
        "llm": "llm",
        "tool": "tool",
        "retriever": "retriever",
        "chain": "chain",
        "agent": "chain",
        "prompt": "llm",
    }
    return mapping.get(run_type, "chain")
