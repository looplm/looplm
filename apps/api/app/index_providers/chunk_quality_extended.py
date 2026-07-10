"""Opt-in extended passes for a chunk-quality run.

The base families are free and always run (:mod:`chunk_quality`); these passes
cost LLM/embedding money or depend on data beyond the index (traces, gold
datasets), so each runs only when enabled in the run's config and is capped by
its own sample size (see ``schemas.chunk_quality.ChunkQualityRunConfig``).

Each pass merges its family + findings into the shared report and persists the
interim results, so the UI shows families appearing while the run is live. A
pass that cannot run (missing LLM config, no labeled gold cases, provider
capability gap) reports ``{"available": false, "reason": ...}`` instead of
failing the run; only an unexpected error additionally leaves a warn finding.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.index_providers.base import BaseIndexProvider
from app.index_providers.chunk_quality import ChunkQualityReport, compute_score
from app.index_providers.chunk_quality_common import Finding, as_text
from app.models.chunk_quality import ChunkQualityRun
from app.services.analysis_llm import (
    AnalysisLlmConfigError,
    AnalysisLlmService,
    LlmUsageInfo,
)
from app.services.chunk_claim_boundary import run_claim_boundary_pass
from app.services.chunk_cohesion import analyze_cohesion
from app.services.chunk_judge_common import AiJudgeChunk, usage_dict
from app.services.chunk_retrieval_frequency import (
    analyze_frequency,
    frequency_from_probe,
    frequency_from_traces,
)
from app.services.chunk_standalone_judge import judge_standalone, summarize_standalone
from app.services.llm_usage_tracker import record_llm_usage
from app.services.query_embedding import build_query_embedder

logger = logging.getLogger(__name__)

_PASS_ORDER = ("standalone", "cohesion", "retrieval_frequency", "claim_boundary")


def _subsample(docs: list[dict], target: int) -> list[dict]:
    """Evenly-spaced subsample of the run's docs, preserving the sample's spread."""
    n = len(docs)
    if n <= target:
        return list(docs)
    step = n / target
    return [docs[int(i * step)] for i in range(target)]


def _judge_chunks(docs: list[dict], *, id_field: str | None, text_field: str) -> list[AiJudgeChunk]:
    chunks = []
    for d in docs:
        text = as_text(d.get(text_field))
        if not text.strip():
            continue
        cid = as_text(d.get(id_field)) if id_field else ""
        chunks.append(AiJudgeChunk(chunk_id=cid or f"sample-{len(chunks)}", text=text))
    return chunks


async def run_extended_passes(
    *,
    provider: BaseIndexProvider,
    report: ChunkQualityReport,
    config: dict,
    db_factory,
    project_id: UUID,
    run_id: UUID,
) -> None:
    """Run the enabled passes, merging each into ``report`` (see module docstring)."""
    passes = config.get("passes") or {}
    enabled = [
        name for name in _PASS_ORDER
        if isinstance(passes.get(name), dict) and passes[name].get("enabled")
    ]
    if not enabled:
        return

    async with db_factory() as db:
        project_settings = await AnalysisLlmService.load_project_settings(db, project_id)

    llm: AnalysisLlmService | None = None
    llm_error: str | None = None
    if "standalone" in enabled or "claim_boundary" in enabled:
        try:
            llm = AnalysisLlmService(project_settings=project_settings)
        except AnalysisLlmConfigError as exc:
            llm_error = str(exc)

    embedder = None
    if "cohesion" in enabled:
        embedder = build_query_embedder(project_settings)

    text_field = report.fields.get("text")
    id_field = report.fields.get("id")

    try:
        for name in enabled:
            cfg = passes[name]
            usage: LlmUsageInfo | None = None
            try:
                if name == "standalone":
                    metrics, findings, usage = await _run_standalone(
                        report, cfg, llm=llm, llm_error=llm_error,
                        id_field=id_field, text_field=text_field,
                    )
                elif name == "cohesion":
                    metrics, findings = await _run_cohesion(
                        report, cfg, embedder=embedder,
                        id_field=id_field, text_field=text_field,
                    )
                elif name == "retrieval_frequency":
                    metrics, findings = await _run_retrieval_frequency(
                        report, cfg, provider=provider, db_factory=db_factory,
                        project_id=project_id, id_field=id_field,
                    )
                else:  # claim_boundary
                    metrics, findings, usage = await _run_claim_boundary(
                        cfg, provider=provider, db_factory=db_factory,
                        project_id=project_id, llm=llm, llm_error=llm_error,
                    )
            except Exception as exc:  # noqa: BLE001 — one broken pass must not fail the run
                logger.exception("Chunk quality pass %s failed for run %s", name, run_id)
                metrics = {"available": False, "reason": str(exc)}
                findings = [Finding(
                    family=name, severity="warn",
                    title=f"{name.replace('_', ' ')} pass failed",
                    message=f"The pass errored and was skipped: {exc}",
                )]

            report.families[name] = metrics
            report.findings.extend(findings)
            report.score = compute_score(report.findings)
            if usage is not None:
                report.usage[name] = usage_dict(usage)

            await _persist_interim(
                db_factory, run_id=run_id, report=report,
                project_id=project_id, pass_name=name, usage=usage, llm=llm,
            )
    finally:
        if embedder is not None:
            try:
                await embedder.aclose()
            except Exception:
                logger.debug("Embedder aclose failed", exc_info=True)


async def _run_standalone(
    report: ChunkQualityReport, cfg: dict, *,
    llm: AnalysisLlmService | None, llm_error: str | None,
    id_field: str | None, text_field: str | None,
) -> tuple[dict, list[Finding], LlmUsageInfo | None]:
    if llm is None:
        return {"available": False, "reason": llm_error or "analysis LLM not configured"}, [], None
    if not text_field or not report.docs:
        return {"available": False, "reason": "no text field detected in the sample"}, [], None

    sample = _subsample(report.docs, int(cfg.get("sample_size") or 200))
    chunks = _judge_chunks(sample, id_field=id_field, text_field=text_field)
    if not chunks:
        return {"available": False, "reason": "no non-empty chunks in the sample"}, [], None

    verdicts, usage = await judge_standalone(llm, chunks)
    texts_by_id = {c.chunk_id: c.text for c in chunks}
    metrics, findings = summarize_standalone(
        verdicts, sampled=len(chunks), texts_by_id=texts_by_id
    )
    return metrics, findings, usage


async def _run_cohesion(
    report: ChunkQualityReport, cfg: dict, *,
    embedder, id_field: str | None, text_field: str | None,
) -> tuple[dict, list[Finding]]:
    if embedder is None:
        return {"available": False, "reason": "no embedding model configured"}, []
    if not text_field or not report.docs:
        return {"available": False, "reason": "no text field detected in the sample"}, []
    return await analyze_cohesion(
        embedder,
        report.docs,
        text_field=text_field,
        id_field=id_field,
        sample_size=int(cfg.get("sample_size") or 150),
        max_sentences=int(cfg.get("max_sentences") or 30),
    )


async def _run_retrieval_frequency(
    report: ChunkQualityReport, cfg: dict, *,
    provider: BaseIndexProvider, db_factory, project_id: UUID, id_field: str | None,
) -> tuple[dict, list[Finding]]:
    if not id_field:
        return {"available": False, "reason": "no chunk id field detected in the sample"}, []

    source = cfg.get("source") or "traces"
    window_days = int(cfg.get("window_days") or 30)
    dataset_id = cfg.get("dataset_id")
    dataset_uuid = UUID(str(dataset_id)) if dataset_id else None

    async with db_factory() as db:
        if source == "probe":
            counter, events = await frequency_from_probe(
                db, provider, project_id,
                dataset_id=dataset_uuid,
                max_queries=int(cfg.get("max_queries") or 100),
            )
        else:
            from app.models.project import Project

            project = await db.get(Project, project_id)
            if project is None:
                return {"available": False, "reason": "project not found"}, []
            counter, events = await frequency_from_traces(
                db, project, window_days=window_days
            )

    sampled_ids = {
        as_text(d.get(id_field)) for d in report.docs if as_text(d.get(id_field)).strip()
    }
    title_field = report.fields.get("title")
    titles_by_id = {
        as_text(d.get(id_field)): as_text(d.get(title_field))
        for d in report.docs
        if title_field and as_text(d.get(id_field)).strip()
    }
    return analyze_frequency(
        counter, sampled_ids,
        source=source,
        window_days=window_days if source == "traces" else None,
        events_scanned=events,
        titles_by_id=titles_by_id,
    )


async def _run_claim_boundary(
    cfg: dict, *,
    provider: BaseIndexProvider, db_factory, project_id: UUID,
    llm: AnalysisLlmService | None, llm_error: str | None,
) -> tuple[dict, list[Finding], LlmUsageInfo | None]:
    if llm is None:
        return {"available": False, "reason": llm_error or "analysis LLM not configured"}, [], None
    dataset_id = cfg.get("dataset_id")
    async with db_factory() as db:
        metrics, findings, usage = await run_claim_boundary_pass(
            db, llm, provider, project_id,
            dataset_id=UUID(str(dataset_id)) if dataset_id else None,
            max_cases=int(cfg.get("max_cases") or 50),
        )
    return metrics, findings, usage


async def _persist_interim(
    db_factory, *,
    run_id: UUID,
    report: ChunkQualityReport,
    project_id: UUID,
    pass_name: str,
    usage: LlmUsageInfo | None,
    llm: AnalysisLlmService | None,
) -> None:
    """Persist the merged report and, when a pass spent LLM tokens, its usage row."""
    async with db_factory() as db:
        run = (
            await db.execute(select(ChunkQualityRun).where(ChunkQualityRun.id == run_id))
        ).scalar_one_or_none()
        if run is not None:
            run.results = report.to_dict()
        if usage is not None and usage.total_tokens and llm is not None:
            await record_llm_usage(
                db,
                project_id=project_id,
                service_name="chunk_quality",
                function_name=pass_name,
                provider=llm.provider,
                model=llm.model,
                usage=usage,
            )
        await db.commit()
