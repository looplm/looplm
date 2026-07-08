"""Background worker for failure-mode analysis of negative-feedback traces.

Two stages:
1. Per-trace diagnosis — each selected trace (question, retrieved RAG context,
   assembled context, answer, error, and the user's complaint) is classified into
   a single root-cause category from a fixed RAG failure taxonomy via one LLM call.
2. Clustering — the diagnoses are grouped into named failure modes via one more
   LLM call, so the user sees *what* is going wrong and *why*, not just per-case.

Trace serialization (``serialize_trace_for_diagnosis``) runs in the request that
launches the job, where the traces + spans are already loaded; only the compact
serialized cases are handed to this worker (mirrors ``feedback_themes`` passing
plain comment dicts rather than ORM objects).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from app.routers.top_questions_worker import _parse_json_array
from app.services.rag_pipeline import build_rag_pipeline
from app.services.retrieval_config import extract_retrieval_context_from_payload

logger = logging.getLogger(__name__)

_failure_mode_tasks: dict[UUID, asyncio.Task] = {}

# Fixed RAG failure taxonomy. The diagnosis LLM must pick one of these keys and
# may coin a new snake_case key only when none genuinely fits (per the product
# decision). Keep the frontend category map (feedback-failure-modes-tab) in sync.
FAILURE_CATEGORIES: dict[str, str] = {
    "retrieval": (
        "Retrieval miss — the knowledge base likely contains the answer, but the "
        "right source/chunk was not retrieved (wrong, missing, or low-ranked sources)."
    ),
    "generation": (
        "Generation error — relevant context WAS retrieved, but the answer "
        "hallucinated, contradicted the sources, or ignored/misused them."
    ),
    "long_context": (
        "Lost in the middle / long context — the needed information was present in "
        "the retrieved context but the model overlooked it, likely due to context "
        "length or the position of the relevant passage."
    ),
    "query": (
        "User prompt issue — the user's question was ambiguous, underspecified, "
        "contained a typo, or rested on a wrong assumption."
    ),
    "knowledge_gap": (
        "Knowledge gap — the answer does not exist in the knowledge base at all; "
        "retrieval could never have succeeded."
    ),
    "refusal": (
        "Refusal or formatting — the assistant wrongly refused or deflected, or "
        "answered in the wrong format, language, or level of detail."
    ),
    "other": "Other — none of the above genuinely fits.",
}

_DIAGNOSE_SYSTEM_PROMPT = (
    "You are an LLM failure analyst for a retrieval-augmented (RAG) assistant. You "
    "are given ONE case where a user left NEGATIVE feedback: the user question, the "
    "retrieval funnel and retrieved sources, the assembled context, the assistant's "
    "answer, any error, and the user's complaint. Determine the single most likely "
    "ROOT CAUSE of the failure.\n\n"
    "Choose exactly one category key from this fixed taxonomy:\n"
    + "\n".join(f'- "{k}": {v}' for k, v in FAILURE_CATEGORIES.items())
    + "\n\nOnly if none of these genuinely fits may you return a new lowercase "
    "snake_case category key. Weigh the evidence: if good sources were retrieved and "
    "used but the answer is still wrong, prefer \"generation\"; if the sources needed "
    "were never retrieved, prefer \"retrieval\"; if they were retrieved but buried, "
    'prefer "long_context".\n\n'
    "If a FEEDBACK QUALITY VERDICT is present, use it as a prior: a \"suspicious\" "
    "verdict means the negative rating may not reflect a genuine model failure "
    "(e.g. user confusion or an off-topic complaint) — lean toward \"query\" or "
    "\"other\" unless the trace clearly shows a real failure; a \"helpful\" verdict "
    "confirms the complaint is a genuine failure worth attributing to a stage.\n\n"
    "Return ONLY a JSON object, no markdown:\n"
    '{"category": "<key>", "explanation": "<one or two sentences citing concrete '
    'evidence from the case>", "confidence": <number 0.0-1.0>}'
)

_CLUSTER_SYSTEM_PROMPT = (
    "You are an LLM failure analyst. You receive a numbered list of diagnosed "
    "failure cases from a RAG assistant. Each line shows the case index, its "
    "root-cause category, the user question, and a short explanation. Group cases "
    "that share the SAME underlying failure mode into clusters.\n\n"
    "Instructions:\n"
    "1. Group by the concrete shared failure mode, not only by category — two "
    "retrieval misses about unrelated topics can be separate clusters.\n"
    "2. Give each cluster a short, specific label (e.g. \"Missing step-by-step WinEV "
    "guides\", not just \"Retrieval\").\n"
    "3. Set \"category\" to the dominant root-cause category key of the cluster.\n"
    "4. Write a one-line \"description\" of what goes wrong and a one-line "
    "\"recommendation\" for how to fix it.\n"
    "5. List ALL case indices in each cluster in \"case_indices\". Every index must "
    "appear in exactly one cluster — do not drop any.\n\n"
    "Return a JSON array sorted by count descending, at most 12 clusters:\n"
    '[{"label": "...", "category": "...", "description": "...", '
    '"recommendation": "...", "case_indices": [1, 4, ...]}]\n\n'
    "Return ONLY the JSON array, no markdown or explanation."
)

# Bounds on the per-trace diagnosis input to control token cost.
_QUESTION_MAX = 1500
_CONTEXT_MAX = 5000
_ANSWER_MAX = 2500
_COMMENT_MAX = 600
_ANSWER_PREVIEW_MAX = 400
_DIAGNOSE_INPUT_MAX = 12000


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def serialize_trace_for_diagnosis(
    trace,
    span_names: dict[str, str],
    *,
    comment: str | None,
    feedback_value,
    verdict: str | None = None,
    reasoning: str | None = None,
) -> dict:
    """Build the compact diagnosis payload for one trace.

    Returns ``{"question", "answer_preview", "serialized"}``. ``serialized`` is the
    full bounded context block handed to the diagnosis LLM. The RAG funnel, sources,
    and assembled context come from :func:`build_rag_pipeline` when the trace is a RAG
    trace; otherwise it falls back to extracting retrieval context from the output
    payload. Runs in the launching request (spans are loaded there).
    """
    from app.routers.top_questions import _extract_user_question

    view = build_rag_pipeline(trace, span_names)
    question = (_extract_user_question(trace.input) or "").strip()
    parts: list[str] = []

    if view.available:
        answer = (view.answer or _stringify(trace.output)).strip()
        c = view.counts
        parts.append(
            f"RETRIEVAL FUNNEL: retrieved={c.found}, used_in_context={c.used_in_context}, "
            f"cited={c.cited}"
        )
        if view.judge is not None and view.judge.passed is not None:
            parts.append(f"SELF-CHECK JUDGE: passed={view.judge.passed}")
        src_lines = []
        for s in view.sources[:15]:
            tag = "USED_IN_ANSWER" if s.selected else "retrieved_only"
            score = f" score={round(s.score, 3)}" if isinstance(s.score, (int, float)) else ""
            title = (s.title or s.url or "").strip()
            src_lines.append(f"- [{tag}]{score} {title}"[:300])
        if src_lines:
            parts.append("RETRIEVED SOURCES:\n" + "\n".join(src_lines))
        if view.assembled_context:
            parts.append("ASSEMBLED CONTEXT (excerpt):\n" + view.assembled_context[:_CONTEXT_MAX])
    else:
        answer = _stringify(trace.output).strip()
        ctx = (
            extract_retrieval_context_from_payload(trace.output, max_chars=_CONTEXT_MAX)
            if isinstance(trace.output, dict)
            else None
        )
        if ctx:
            parts.append("RETRIEVED CONTEXT (excerpt):\n" + ctx)
        else:
            parts.append(
                "RETRIEVED CONTEXT: none captured — retrieval spans are not "
                "instrumented for this trace, so a retrieval miss cannot be ruled out."
            )

    error = (trace.error_message or "").strip()
    error_spans = [
        f"- {s.name}: {(s.error_message or '').strip()[:300]}"
        for s in (trace.spans or [])
        if getattr(s, "status", None) == "error"
    ]

    diag: list[str] = [f"USER QUESTION:\n{question[:_QUESTION_MAX] or '(empty)'}"]
    diag.extend(parts)
    diag.append(f"ASSISTANT ANSWER:\n{answer[:_ANSWER_MAX] or '(empty)'}")
    if error:
        diag.append(f"TRACE ERROR: {error[:600]}")
    if error_spans:
        diag.append("FAILED STEPS:\n" + "\n".join(error_spans[:8]))
    if comment and comment.strip():
        diag.append(f"USER NEGATIVE FEEDBACK COMMENT:\n{comment.strip()[:_COMMENT_MAX]}")
    if verdict and verdict.strip():
        line = f"FEEDBACK QUALITY VERDICT: {verdict.strip()}"
        if reasoning and reasoning.strip():
            line += f" — {reasoning.strip()[:400]}"
        diag.append(line)

    return {
        "question": question[:_QUESTION_MAX] or None,
        "answer_preview": answer[:_ANSWER_PREVIEW_MAX] or None,
        "serialized": "\n\n".join(diag),
    }


def _parse_json_object(text: str) -> dict:
    """Parse a JSON object from an LLM response, handling markdown fences."""
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


async def _abort_if_cancelled(db, analysis_id: UUID) -> None:
    """Cooperatively honor a stop request, even from another worker/replica."""
    from app.models.feedback_eval import FailureModeAnalysis

    db.expire_all()
    current = await db.get(FailureModeAnalysis, analysis_id)
    if current is None or current.status == "cancelled":
        raise asyncio.CancelledError()


async def _diagnose(llm, serialized: str):
    """One diagnosis LLM call → (diagnosis dict, usage|None). Defaults to 'other'."""
    default = {"category": "other", "explanation": "", "confidence": None}
    try:
        content, usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": _DIAGNOSE_SYSTEM_PROMPT},
                {"role": "user", "content": serialized[:_DIAGNOSE_INPUT_MAX]},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("Failure-mode diagnosis call failed: %s", exc)
        return default, None

    parsed = _parse_json_object(content)
    category = parsed.get("category")
    if not isinstance(category, str) or not category.strip():
        category = "other"
    confidence = parsed.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    return {
        "category": category.strip()[:40],
        "explanation": str(parsed.get("explanation", ""))[:600],
        "confidence": confidence,
    }, usage


def _case_public(c: dict) -> dict:
    """Case dict for storage/response — drops the bulky ``serialized`` field."""
    return {
        "trace_id": c.get("trace_id"),
        "question": c.get("question"),
        "answer_preview": c.get("answer_preview"),
        "comment": c.get("comment"),
        "feedback_value": c.get("feedback_value"),
        "category": c.get("category", "other"),
        "explanation": c.get("explanation", ""),
        "confidence": c.get("confidence"),
    }


def _build_clusters(raw_clusters: list[dict], cases: list[dict]) -> list[dict]:
    """Resolve LLM case_indices (1-based) to full cases, losslessly.

    Any case the clusterer failed to assign is grouped into a fallback cluster by
    category so no diagnosed case is ever dropped from the results.
    """
    clusters: list[dict] = []
    claimed: set[int] = set()

    for rc in raw_clusters:
        indices = rc.get("case_indices") or []
        members: list[dict] = []
        cat_counts: dict[str, int] = {}
        for i in indices:
            if isinstance(i, int) and 1 <= i <= len(cases) and (i - 1) not in claimed:
                claimed.add(i - 1)
                c = cases[i - 1]
                members.append(_case_public(c))
                cat = c.get("category", "other")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if not members:
            continue
        dominant = max(cat_counts, key=cat_counts.get) if cat_counts else "other"
        clusters.append({
            "label": str(rc.get("label", "Unlabeled"))[:200],
            "category": str(rc.get("category") or dominant)[:40],
            "count": len(members),
            "description": str(rc.get("description", ""))[:600],
            "recommendation": str(rc.get("recommendation", ""))[:600],
            "category_counts": cat_counts,
            "cases": members,
        })

    leftover = [i for i in range(len(cases)) if i not in claimed]
    if leftover:
        by_cat: dict[str, list[int]] = {}
        for i in leftover:
            by_cat.setdefault(cases[i].get("category", "other"), []).append(i)
        for cat, idxs in by_cat.items():
            clusters.append({
                "label": f"Unclustered: {cat}",
                "category": cat,
                "count": len(idxs),
                "description": "Cases the clusterer did not assign to a named failure mode.",
                "recommendation": "",
                "category_counts": {cat: len(idxs)},
                "cases": [_case_public(cases[i]) for i in idxs],
            })

    clusters.sort(key=lambda x: x["count"], reverse=True)
    clusters = clusters[:12]
    for rank, c in enumerate(clusters, 1):
        c["rank"] = rank
    return clusters


async def run_failure_mode_analysis(
    analysis_id: UUID,
    cases: list[dict],
    user_settings: dict | None,
    db_factory,
) -> None:
    """Diagnose each negative-feedback trace, then cluster into failure modes."""
    from app.models.feedback_eval import FailureModeAnalysis
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
    from app.services.llm_usage_tracker import record_llm_usage

    async with db_factory() as db:
        analysis = await db.get(FailureModeAnalysis, analysis_id)
        if analysis is None:
            logger.error("Failure-mode analysis %s not found; aborting", analysis_id)
            _failure_mode_tasks.pop(analysis_id, None)
            return

        try:
            llm = AnalysisLlmService(user_settings=user_settings)
        except AnalysisLlmConfigError as e:
            analysis.status = "failed"
            analysis.error = str(e)
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
            _failure_mode_tasks.pop(analysis_id, None)
            return

        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # Stage 1 — per-trace root-cause diagnosis.
            for idx, case in enumerate(cases):
                await _abort_if_cancelled(db, analysis_id)
                diag, usage = await _diagnose(llm, case["serialized"])
                case.update(diag)
                if usage is not None:
                    await record_llm_usage(
                        db,
                        project_id=analysis.project_id,
                        service_name="failure_modes",
                        function_name="diagnose_trace",
                        provider=llm.provider,
                        model=llm.model,
                        usage=usage,
                        request_metadata={"analysis_id": str(analysis_id), "case": idx + 1},
                    )
                analysis = await db.get(FailureModeAnalysis, analysis_id)
                analysis.processed_traces = idx + 1
                await db.commit()

            category_counts: dict[str, int] = {}
            for c in cases:
                cat = c.get("category", "other")
                category_counts[cat] = category_counts.get(cat, 0) + 1

            # Stage 2 — cluster the diagnoses into named failure modes.
            await _abort_if_cancelled(db, analysis_id)
            numbered = [
                f'{i}. [{c.get("category", "other")}] '
                f'{(c.get("question") or "")[:200]} :: {(c.get("explanation") or "")[:220]}'
                for i, c in enumerate(cases, 1)
            ]
            text, usage = await llm.tracked_chat_completion(
                messages=[
                    {"role": "system", "content": _CLUSTER_SYSTEM_PROMPT},
                    {"role": "user", "content": "\n".join(numbered)},
                ],
                temperature=0.1,
            )
            await record_llm_usage(
                db,
                project_id=analysis.project_id,
                service_name="failure_modes",
                function_name="cluster_failure_modes",
                provider=llm.provider,
                model=llm.model,
                usage=usage,
                request_metadata={"analysis_id": str(analysis_id), "case_count": len(cases)},
            )

            clusters = _build_clusters(_parse_json_array(text), cases)

            db.expire_all()
            analysis = await db.get(FailureModeAnalysis, analysis_id)
            if analysis is None or analysis.status == "cancelled":
                return
            analysis.results = clusters
            analysis.category_counts = category_counts
            analysis.processed_traces = len(cases)
            analysis.status = "completed"
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except asyncio.CancelledError:
            logger.info("Failure-mode analysis %s stopped", analysis_id)
            raise
        except Exception as e:
            logger.exception("Failure-mode analysis failed")
            analysis = await db.get(FailureModeAnalysis, analysis_id)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
        finally:
            _failure_mode_tasks.pop(analysis_id, None)
