"""Tests for issue diagnosis: the diagnosis parser and the diagnose_issues pass."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.models import (
    Integration,
    Issue,
    IssueEvidence,
    IssueEvent,
    IssueStatus,
    SignalType,
)
from app.services.analysis_llm import LlmUsageInfo
from app.services.engine.engine_service import diagnose_issues, parse_diagnosis


class FakeDiagnosisLlm:
    provider = "openai"
    model = "gpt-test"

    def __init__(self, payload: dict):
        self._payload = payload
        self.calls = 0

    async def tracked_chat_completion(self, messages, **kwargs):
        self.calls += 1
        return json.dumps(self._payload), LlmUsageInfo(0, 0, 0, None, 0, 0, 0)


# ── Parser ─────────────────────────────────────────────────────────

def test_parse_diagnosis_valid():
    d = parse_diagnosis(json.dumps({"root_cause": "Tool times out.", "suggested_fix": "Add retry."}))
    assert d is not None
    assert d.root_cause == "Tool times out."
    assert d.suggested_fix == "Add retry."


def test_parse_diagnosis_requires_root_cause():
    assert parse_diagnosis(json.dumps({"suggested_fix": "x"})) is None
    assert parse_diagnosis("garbage") is None
    assert parse_diagnosis(json.dumps({"root_cause": "  "})) is None


def test_parse_diagnosis_fix_optional():
    d = parse_diagnosis(json.dumps({"root_cause": "Because reasons."}))
    assert d is not None and d.suggested_fix is None


# ── diagnose_issues pass ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_diagnose_issues_fills_root_cause_and_fix(
    db_session, test_project, test_integration: Integration
):
    issue = Issue(
        id=uuid4(),
        project_id=test_project.id,
        title="Search tool keeps failing",
        category="tool_failure",
        severity="high",
        status=IssueStatus.open,
        signal_types=["explicit_failure"],
    )
    db_session.add(issue)
    await db_session.flush()
    db_session.add(
        IssueEvidence(
            issue_id=issue.id,
            trace_id=None,
            signal_type=SignalType.explicit_failure,
            detail="ToolError: search timeout after 30s",
        )
    )
    await db_session.commit()

    llm = FakeDiagnosisLlm({"root_cause": "The search tool times out.", "suggested_fix": "Add a retry with backoff."})
    result = await diagnose_issues(db_session, test_project.id, llm=llm)

    assert result == {"diagnosed": 1}
    assert llm.calls == 1
    await db_session.refresh(issue)
    assert issue.root_cause == "The search tool times out."
    assert issue.suggested_fix == "Add a retry with backoff."

    events = (
        await db_session.execute(
            select(IssueEvent).where(IssueEvent.issue_id == issue.id)
        )
    ).scalars().all()
    assert any(e.event_type == "diagnosed" for e in events)


@pytest.mark.asyncio
async def test_diagnose_issues_noop_without_llm(db_session, test_project):
    assert await diagnose_issues(db_session, test_project.id, llm=None) == {"diagnosed": 0}


@pytest.mark.asyncio
async def test_diagnose_issues_skips_already_diagnosed(
    db_session, test_project, test_integration: Integration
):
    issue = Issue(
        id=uuid4(),
        project_id=test_project.id,
        title="Already diagnosed",
        severity="low",
        status=IssueStatus.open,
        signal_types=["explicit_failure"],
        root_cause="known",
    )
    db_session.add(issue)
    await db_session.commit()

    llm = FakeDiagnosisLlm({"root_cause": "new", "suggested_fix": "new"})
    result = await diagnose_issues(db_session, test_project.id, llm=llm)
    assert result == {"diagnosed": 0}
    assert llm.calls == 0
