"""Organize prompts into an editable hierarchy via one LLM call.

Mirrors `engine/clustering.py`: the model call is isolated behind
``suggest_clusters`` and the response parsing is a pure function
(``parse_clustering_response``) so both can be tested without a live model.
The suggestion writes ``Prompt.cluster_path`` (an ordered list like
``["Graders", "Conciseness"]``); the user can edit it afterward.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Integration, IntegrationType, Prompt
from app.services.analysis_llm import AnalysisLlmService

logger = logging.getLogger(__name__)

_MAX_PROMPTS_PER_CALL = 80
_MAX_DEPTH = 3
_SNIPPET_LEN = 200
_UNGROUPED = ["Ungrouped"]

_SYSTEM_PROMPT = (
    "You organize a software project's LLM prompts into a clear, browsable "
    "hierarchy. You are given a numbered list of prompts (name, file, snippet). "
    "Group them into a tree of categories — broad theme first, then sub-theme.\n\n"
    "Return ONLY a JSON object of the form:\n"
    '{"clusters": [{"path": ["Theme", "Sub-theme"], "prompt_indices": [0, 2]}], '
    '"summary": "one sentence"}\n\n'
    "Rules:\n"
    "- Every prompt index (0-based) must appear in exactly one cluster.\n"
    f"- path: 1 to {_MAX_DEPTH} short, human-readable level names (Title Case), "
    "from general to specific. Reuse the same wording for prompts that belong "
    "together so the tree stays shallow and tidy.\n"
    "- Prefer a handful of meaningful groups over one bucket per prompt.\n"
    "- Base groups on purpose/domain (e.g. 'Graders', 'Summarization', "
    "'System prompts'), not on file path alone."
)


def _build_user_message(items: list[dict]) -> str:
    payload = [
        {
            "index": it["index"],
            "name": it["name"],
            "file": it.get("file_path", ""),
            "snippet": (it.get("snippet") or "")[:_SNIPPET_LEN],
        }
        for it in items
    ]
    return "PROMPTS:\n" + json.dumps(payload, ensure_ascii=False)


def _clean_path(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return list(_UNGROUPED)
    path: list[str] = []
    for level in raw[:_MAX_DEPTH]:
        s = str(level).strip()
        if s:
            path.append(s[:120])
    return path or list(_UNGROUPED)


def parse_clustering_response(content: str, n_prompts: int) -> dict[int, list[str]]:
    """Parse the model JSON into ``{prompt_index: cluster_path}``.

    Clamps out-of-range indices, caps depth, and assigns any prompt the model
    forgot to ``["Ungrouped"]`` so nothing is silently lost.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {}

    assignment: dict[int, list[str]] = {}
    for cluster in data.get("clusters", []) or []:
        if not isinstance(cluster, dict):
            continue
        path = _clean_path(cluster.get("path"))
        for idx in cluster.get("prompt_indices", []) or []:
            if isinstance(idx, int) and 0 <= idx < n_prompts and idx not in assignment:
                assignment[idx] = path

    for idx in range(n_prompts):
        assignment.setdefault(idx, list(_UNGROUPED))
    return assignment


async def suggest_clusters(
    items: list[dict],
    llm: AnalysisLlmService,
) -> tuple[dict[int, list[str]], str, object]:
    """Return ``({index: path}, summary, usage)`` for the given prompt items."""
    if not items:
        return {}, "", None

    # Chunk large sets; paths may differ slightly across chunks but nothing is lost.
    assignment: dict[int, list[str]] = {}
    summary = ""
    last_usage = None
    for start in range(0, len(items), _MAX_PROMPTS_PER_CALL):
        chunk = items[start : start + _MAX_PROMPTS_PER_CALL]
        # Re-index the chunk 0-based for the model, then map back.
        local = [{**it, "index": i} for i, it in enumerate(chunk)]
        content, usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(local)},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        last_usage = usage
        local_assign = parse_clustering_response(content, len(chunk))
        for local_idx, path in local_assign.items():
            assignment[chunk[local_idx]["index"]] = path
    return assignment, summary, last_usage


async def cluster_project_prompts(
    db: AsyncSession,
    project_id: UUID,
    *,
    user_settings: dict | None = None,
) -> int:
    """Re-cluster all github-sourced prompts for a project. Returns count clustered.

    Best-effort: raises only on hard failures the caller chooses to surface;
    callers in the extraction pipeline wrap this so a clustering hiccup never
    discards already-saved prompts.
    """
    integration = (
        await db.execute(
            select(Integration).where(
                Integration.project_id == project_id,
                Integration.type == IntegrationType.github,
            )
        )
    ).scalar_one_or_none()
    if not integration:
        return 0

    prompts = list(
        (
            await db.execute(
                select(Prompt)
                .where(Prompt.integration_id == integration.id)
                .order_by(Prompt.name)
            )
        ).scalars().all()
    )
    if not prompts:
        return 0

    items = [
        {
            "index": i,
            "name": p.name,
            "file_path": (p.prompt_metadata or {}).get("file_path", ""),
            "snippet": p.template or "",
        }
        for i, p in enumerate(prompts)
    ]

    llm = AnalysisLlmService(user_settings=user_settings)
    assignment, _summary, usage = await suggest_clusters(items, llm)

    for i, p in enumerate(prompts):
        p.cluster_path = assignment.get(i, list(_UNGROUPED))
    await db.commit()

    if usage is not None:
        from app.services.llm_usage_tracker import record_llm_usage
        await record_llm_usage(
            db,
            project_id=project_id,
            service_name="prompt_clustering",
            function_name="cluster_project_prompts",
            provider=llm.provider,
            model=llm.model,
            usage=usage,
            request_metadata={"prompt_count": len(prompts)},
        )

    return len(prompts)


async def move_cluster(
    db: AsyncSession,
    project_id: UUID,
    from_path: list[str],
    to_path: list[str],
) -> int:
    """Bulk rename/move: rewrite the cluster_path prefix for every github prompt
    under ``from_path``. Returns the number of prompts updated."""
    integration = (
        await db.execute(
            select(Integration).where(
                Integration.project_id == project_id,
                Integration.type == IntegrationType.github,
            )
        )
    ).scalar_one_or_none()
    if not integration:
        return 0

    from_clean = [s.strip() for s in from_path if str(s).strip()]
    to_clean = [s.strip() for s in to_path if str(s).strip()][:_MAX_DEPTH]
    if not from_clean:
        return 0

    prompts = (
        await db.execute(select(Prompt).where(Prompt.integration_id == integration.id))
    ).scalars().all()
    moved = 0
    for p in prompts:
        path = list(p.cluster_path or [])
        if path[: len(from_clean)] == from_clean:
            p.cluster_path = to_clean + path[len(from_clean):]
            moved += 1
    if moved:
        await db.commit()
    return moved
