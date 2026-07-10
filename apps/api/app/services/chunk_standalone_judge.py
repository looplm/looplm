"""LLM judge for standalone interpretability of chunks — the orphaned-context check.

The classic chunking failure is a chunk that is not interpretable on its own:
"In this case the dose should be halved" with no antecedent for "this case", or
a heading severed from the content it governs. Retrieval returns chunks in
isolation, so such chunks are useless no matter how well they are ranked.

This judge asks one question per chunk, with no query: is the chunk
interpretable standalone, or does it depend on unstated surrounding context?
The dependent rate is a chunking-quality number to track across chunker
versions. Batching, budget settings and JSON tolerance are shared with the
relevance judge via :mod:`chunk_judge_common`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.chunk_judge_common import (
    AiJudgeChunk,
    add_usage,
    batch_chunks,
    clean,
    empty_usage,
    extract_json_object,
)

DEFAULT_STANDALONE_INSTRUCTIONS = (
    "You are assessing chunks from a retrieval index. Each chunk will be shown to a language "
    "model IN ISOLATION, with no surrounding document. For each chunk, judge whether a reader "
    "could correctly interpret it on its own:\n"
    "standalone = true: the chunk is self-contained. Its statements can be understood and "
    "attributed without unstated context.\n"
    "standalone = false: the chunk depends on unstated surrounding context. Signs: unresolved "
    "references (this case, the table above, these values, dieser Fall, siehe oben), a fragment "
    "that starts or ends mid-thought, a bare heading or list continuation, or values whose "
    "subject is never named in the chunk.\n"
    "Judge interpretability only, not usefulness or writing quality. A short but self-contained "
    "chunk is standalone."
)

_MAX_EXAMPLES = 8
_SNIPPET_CHARS = 140


@dataclass
class StandaloneVerdict:
    standalone: bool
    reason: str


def _build_user_prompt(chunks: list[AiJudgeChunk]) -> str:
    lines = ["Chunks:"]
    for i, c in enumerate(chunks, start=1):
        body = clean(c.text) or "(no text)"
        lines.append(f"\n[{i}]\n{body}")
    lines.append(
        '\nReturn ONLY a JSON object of the form {"verdicts": [{"chunk": 1, "standalone": true, '
        '"reason": "..."}, ...]}, one entry per chunk number above. Keep each reason under 15 '
        "words. No prose outside the JSON."
    )
    return "\n".join(lines)


def _parse_verdicts(content: str, chunk_count: int) -> dict[int, StandaloneVerdict]:
    """``{1-based chunk number: verdict}``, dropping anything malformed."""
    data = extract_json_object(content)
    entries = data.get("verdicts") if data else None
    if not isinstance(entries, list):
        return {}
    out: dict[int, StandaloneVerdict] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        n, s = e.get("chunk"), e.get("standalone")
        if (
            isinstance(n, int)
            and not isinstance(n, bool)
            and 1 <= n <= chunk_count
            and isinstance(s, bool)
        ):
            out[n] = StandaloneVerdict(standalone=s, reason=str(e.get("reason") or "")[:200])
    return out


async def judge_standalone(
    llm: AnalysisLlmService,
    chunks: list[AiJudgeChunk],
    *,
    instructions: str | None = None,
    progress_cb=None,
) -> tuple[dict[str, StandaloneVerdict], LlmUsageInfo]:
    """Judge each chunk's standalone interpretability. Returns ``{chunk_id: verdict}``.

    Chunks go out in full, split into context-budgeted batches. Chunks the model
    omits or answers invalidly for are absent from the result — a partial
    response never invents verdicts. ``progress_cb(done, total)`` is awaited
    after each batch with cumulative chunk counts.
    """
    system = (instructions or DEFAULT_STANDALONE_INSTRUCTIONS).strip()
    batches = batch_chunks(chunks, fixed_texts=(system,))

    verdicts: dict[str, StandaloneVerdict] = {}
    usage = empty_usage()
    done = 0
    for batch in batches:
        content, batch_usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_prompt(batch)},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        add_usage(usage, batch_usage)
        for n, v in _parse_verdicts(content, len(batch)).items():
            verdicts[batch[n - 1].chunk_id] = v
        done += len(batch)
        if progress_cb is not None:
            await progress_cb(done, len(chunks))
    return verdicts, usage


def summarize_standalone(
    verdicts: dict[str, StandaloneVerdict],
    sampled: int,
    *,
    texts_by_id: dict[str, str] | None = None,
) -> tuple[dict, list]:
    """The ``standalone`` family dict + findings from a judged sample."""
    from app.index_providers.chunk_quality_common import Finding, pct

    judged = len(verdicts)
    dependent_ids = [cid for cid, v in verdicts.items() if not v.standalone]
    dependent = len(dependent_ids)
    dependent_pct = pct(dependent, judged)

    examples = []
    for cid in dependent_ids[:_MAX_EXAMPLES]:
        text = (texts_by_id or {}).get(cid, "")
        examples.append({
            "chunk_id": cid,
            "reason": verdicts[cid].reason,
            "snippet": clean(text)[:_SNIPPET_CHARS],
        })

    findings: list[Finding] = []
    if judged and dependent_pct >= 20:
        findings.append(Finding(
            family="standalone",
            severity="critical" if dependent_pct >= 40 else "warn",
            title="Chunks not interpretable standalone",
            message=(
                f"{dependent_pct}% of judged chunks depend on unstated surrounding context, "
                "so they carry little meaning when retrieved in isolation."
            ),
            count=dependent,
            examples=[e["snippet"] for e in examples],
        ))

    metrics = {
        "available": True,
        "sampled": sampled,
        "judged": judged,
        "dependent": dependent,
        "dependent_pct": dependent_pct,
        "examples": examples,
    }
    return metrics, findings
