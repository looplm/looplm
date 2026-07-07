from __future__ import annotations

import pytest


async def _import_run_with_one_result(client, auth_headers) -> dict:
    """Helper: import a small eval run with one result, return the parsed list item."""
    resp = await client.post(
        "/api/evals/import",
        headers=auth_headers,
        json={
            "name": "Test Run",
            "results": [
                {
                    "test_id": "case-1",
                    "pass": False,
                    "reason": "missing citation",
                    "input": "Question for the model",
                    "output": "Actual answer from model",
                    "expected_output": "Expected gold answer",
                    "tags": ["foo"],
                    "graders": {
                        "correctness": {
                            "pass": False,
                            "reason": "Wrong answer",
                            "details": {"diff": "expected != actual"},
                        }
                    },
                    "scores": {"faithfulness": 0.5},
                    "metadata": {
                        "conversation_history": [
                            {"turn": 1, "prompt": "p", "response": "r", "pass": False, "graders": {}},
                            {"turn": 2, "prompt": "p2", "response": "r2", "pass": False, "graders": {}},
                        ]
                    },
                    "turns_to_pass": None,
                }
            ],
        },
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_get_eval_run_returns_lightweight_results(client, auth_headers):
    run_item = await _import_run_with_one_result(client, auth_headers)
    run_id = run_item["id"]

    resp = await client.get(f"/api/evals/{run_id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["results"]) == 1
    r = body["results"][0]

    # Heavy fields must NOT be present in the list payload.
    for forbidden in ("input", "output", "expected_output", "reason", "scores", "metadata"):
        assert forbidden not in r, f"{forbidden} should not appear in lightweight result"

    # Lightweight fields must be present.
    assert r["test_id"] == "case-1"
    assert r["pass"] is False
    assert r["tags"] == ["foo"]
    assert r["turn_count"] == 2

    # Graders are trimmed: pass/reason/skipped only — no `details`.
    assert "correctness" in r["graders"]
    grader = r["graders"]["correctness"]
    assert grader["pass"] is False
    assert grader["reason"] == "Wrong answer"
    assert grader.get("skipped") is False
    assert "details" not in grader


@pytest.mark.asyncio
async def test_get_eval_result_returns_full_payload(client, auth_headers):
    run_item = await _import_run_with_one_result(client, auth_headers)
    run_id = run_item["id"]

    list_resp = await client.get(f"/api/evals/{run_id}", headers=auth_headers)
    result_id = list_resp.json()["results"][0]["id"]

    resp = await client.get(f"/api/evals/{run_id}/results/{result_id}", headers=auth_headers)
    assert resp.status_code == 200
    full = resp.json()

    # Full payload includes the heavy fields.
    assert full["input"] == "Question for the model"
    assert full["output"] == "Actual answer from model"
    assert full["expected_output"] == "Expected gold answer"
    assert full["reason"] == "missing citation"
    assert full["scores"] == {"faithfulness": 0.5}
    assert "conversation_history" in full["metadata"]
    assert full["graders"]["correctness"]["details"] == {"diff": "expected != actual"}


@pytest.mark.asyncio
async def test_execution_status_surfaced_in_list_and_modal(client, auth_headers, db_session, test_project):
    """A degraded row reports execution_status in both the run-detail list and the modal."""
    from uuid import uuid4

    from app.models.models import EvalResult, EvalRun

    run = EvalRun(
        id=uuid4(), project_id=test_project.id, name="Eval: DLQ", source="triggered",
        tags=[], total=0, passed=0, failed=0, grader_summary={}, score_summary={}, run_metadata={},
    )
    db_session.add(run)
    await db_session.flush()
    result = EvalResult(
        id=uuid4(), run_id=run.id, test_id="degraded-case", pass_=False,
        tags=[], graders={}, scores={}, result_metadata={"execution": {"status": "degraded"}},
        execution_status="degraded",
    )
    db_session.add(result)
    await db_session.commit()

    list_resp = await client.get(f"/api/evals/{run.id}", headers=auth_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["results"][0]["execution_status"] == "degraded"

    modal_resp = await client.get(f"/api/evals/{run.id}/results/{result.id}", headers=auth_headers)
    assert modal_resp.status_code == 200
    assert modal_resp.json()["execution_status"] == "degraded"


def test_enrich_result_metadata_surfaces_usage_and_context():
    """The row-modal enrichment pulls target token usage and the full context block."""
    import json as _json

    from app.routers.eval_result_helpers import _enrich_result_metadata

    raw = _json.dumps({
        "answer": "a",
        "formattedContext": "Gefundene Dokumente ...",
        "usage": {"promptTokens": 21186, "completionTokens": 151},
    })
    out = _enrich_result_metadata({"raw_response": raw})
    assert out["target_usage"] == {
        "prompt_tokens": 21186,
        "completion_tokens": 151,
        "total_tokens": 21337,
    }
    assert out["model_context"] == "Gefundene Dokumente ..."

    # snake_case usage is accepted; a payload without usage/context adds nothing.
    snake = _enrich_result_metadata({"raw_response": _json.dumps({"usage": {"prompt_tokens": 5, "completion_tokens": 2}})})
    assert snake["target_usage"]["total_tokens"] == 7
    bare = _enrich_result_metadata({"raw_response": _json.dumps({"answer": "a"})})
    assert "target_usage" not in bare and "model_context" not in bare


@pytest.mark.asyncio
async def test_get_eval_result_404_when_missing(client, auth_headers):
    import uuid

    run_item = await _import_run_with_one_result(client, auth_headers)
    run_id = run_item["id"]
    missing = uuid.uuid4()

    resp = await client.get(f"/api/evals/{run_id}/results/{missing}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_eval_run_accepts_legacy_eval_import_format(client, auth_headers):
    resp = await client.post(
        "/api/evals/import",
        headers=auth_headers,
        json={
            "version": "2024-01-01",
            "name": "Legacy Import",
            "summary": {"total": 1},
            "testCases": [
                {
                    "id": "tc-1",
                    "prompt": "What is 2 + 2?",
                    "expectedAnswer": "4",
                    "teamFilter": ["math"],
                }
            ],
            "results": [
                {
                    "id": "tc-1",
                    "pass": True,
                    "reason": "Correct",
                    "actualAnswer": "4",
                    "customGraders": {
                        "correctness": {
                            "pass": True,
                            "reason": "Matches expected answer",
                        }
                    },
                    "ragasScores": {"faithfulness": 1.0},
                    "toolsCalled": ["calculator"],
                }
            ],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Legacy Import"
    assert data["source"] == "legacy-eval-import"
    assert data["total"] == 1
    assert data["passed"] == 1
