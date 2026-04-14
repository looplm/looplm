from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_project_normalizes_legacy_eval_endpoint_setting(
    client,
    auth_headers,
    db_session,
    test_project,
):
    test_project.settings = {"eval_rde_gpt_endpoint": "https://legacy.example/api"}
    await db_session.commit()
    await db_session.refresh(test_project)

    resp = await client.get(f"/api/projects/{test_project.id}", headers=auth_headers)

    assert resp.status_code == 200
    settings = resp.json()["settings"]
    assert settings["eval_target_endpoint"] == "https://legacy.example/api"
    assert "eval_rde_gpt_endpoint" not in settings


@pytest.mark.asyncio
async def test_patch_project_rewrites_legacy_eval_endpoint_setting(
    client,
    auth_headers,
    db_session,
    test_project,
):
    test_project.settings = {"eval_rde_gpt_endpoint": "https://legacy.example/api"}
    await db_session.commit()

    resp = await client.patch(
        f"/api/projects/{test_project.id}",
        headers=auth_headers,
        json={"settings": {"eval_response_path": "answer"}},
    )

    assert resp.status_code == 200
    settings = resp.json()["settings"]
    assert settings["eval_target_endpoint"] == "https://legacy.example/api"
    assert settings["eval_response_path"] == "answer"
    assert "eval_rde_gpt_endpoint" not in settings

    await db_session.refresh(test_project)
    assert test_project.settings["eval_target_endpoint"] == "https://legacy.example/api"
    assert test_project.settings["eval_response_path"] == "answer"
    assert "eval_rde_gpt_endpoint" not in test_project.settings
