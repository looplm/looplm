from __future__ import annotations

import pytest


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
