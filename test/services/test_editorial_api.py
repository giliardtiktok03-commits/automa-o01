import asyncio
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from app import asgi
from app.controllers.v1 import editorial as controller
from app.controllers.manager.base_manager import TaskQueueFullError
from app.models import const
from app.services import editorial

# Reuse input contracts without making live model calls.
from test.services.test_editorial import workflow_data, decision_data, setup  # noqa: F401


def request(method, path, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=asgi.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(send())


@pytest.fixture
def api(request, monkeypatch):
    body, model, script = request.getfixturevalue("setup")
    monkeypatch.setitem(editorial.config.app, "api_key", "test-mpt-key")

    def immediate(func, **kwargs):
        return func(**kwargs)

    manager = Mock()
    manager.add_task.side_effect = immediate
    monkeypatch.setattr(controller, "task_manager", manager)
    return body, model, script, manager


def test_authentication_runs_before_model_calls(api):
    body, model, _, _ = api
    result = request("POST", "/api/v1/editorial/decompose", json=body.model_dump(mode="json", exclude={"workflow_id", "target_duration_minutes"}))
    assert result.status_code == 401
    model.assert_not_called()


def test_research_route_accepts_a_title_and_nexlev_results(api):
    body, model, _, _ = api
    fields = {name: body.model_dump(mode="json")[name] for name in ("reference", "nexlev", "target_topic", "outlier_threshold")}
    result = request("POST", "/api/v1/editorial/research", headers={"x-api-key": "test-mpt-key"}, json=fields)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["outliers"]["videos"][0]["outlier_ratio"] == 12
    model.assert_not_called()


def test_async_workflow_returns_selected_proposal_script_and_video_payload(api):
    body, model, script, manager = api
    workflow_id = str(uuid4())
    payload = body.model_dump(mode="json")
    payload["workflow_id"] = workflow_id
    headers = {"x-api-key": "test-mpt-key"}
    result = request("POST", "/api/v1/editorial/workflows", json=payload, headers=headers)
    assert result.status_code == 202, result.text
    assert result.json()["data"]["workflow_id"] == workflow_id
    completed = request("GET", f"/api/v1/editorial/workflows/{workflow_id}", headers=headers)
    assert completed.status_code == 200, completed.text
    data = completed.json()["data"]
    assert data["state"] == 1 and data["approval"] == "ai_selected"
    assert data["decomposition"]["selected_id"] == 2
    assert data["script"] == script
    assert data["video_params"]["video_script"] == script
    assert "fingerprint" not in data
    assert model.call_count == 2
    request("POST", "/api/v1/editorial/workflows", json=payload, headers=headers)
    assert manager.add_task.call_count == 1
    assert model.call_count == 2
    payload["target_topic"] = "Outro tema"
    conflict = request("POST", "/api/v1/editorial/workflows", json=payload, headers=headers)
    assert conflict.status_code == 409


def test_queue_rejection_rolls_back_new_checkpoint_and_state(api):
    body, model, _, manager = api
    manager.add_task.side_effect = TaskQueueFullError("full")
    workflow_id = str(uuid4())
    payload = body.model_dump(mode="json")
    payload["workflow_id"] = workflow_id
    result = request("POST", "/api/v1/editorial/workflows", json=payload, headers={"x-api-key": "test-mpt-key"})
    assert result.status_code == 429
    assert editorial.read_workflow(workflow_id) is None
    assert editorial.sm.state.get_task(workflow_id) is None
    model.assert_not_called()


def test_missing_workflow_returns_404_without_creating_a_directory(api):
    workflow_id = str(uuid4())
    result = request("GET", f"/api/v1/editorial/workflows/{workflow_id}", headers={"x-api-key": "test-mpt-key"})
    assert result.status_code == 404
    assert not editorial.workflow_dir(workflow_id, create=False).exists()


def test_empty_research_is_a_validation_error(api):
    body, model, _, _ = api
    payload = body.model_dump(mode="json")
    payload["nexlev"] = {}
    result = request("POST", "/api/v1/editorial/workflows", json=payload, headers={"x-api-key": "test-mpt-key"})
    assert result.status_code == 400
    model.assert_not_called()


def test_get_marks_an_interrupted_running_stage_and_supports_resubmission(api):
    body, model, script, _ = api
    workflow_id = str(uuid4())
    directory = editorial.workflow_dir(workflow_id)
    editorial._save(directory, {"workflow_id": workflow_id, "fingerprint": editorial.fingerprint(body),
                                "kind": "editorial", "stage": "decomposition", "progress": 35,
                                "state": const.TASK_STATE_PROCESSING, "research": editorial.research(body)})
    headers = {"x-api-key": "test-mpt-key"}
    result = request("GET", f"/api/v1/editorial/workflows/{workflow_id}", headers=headers)
    assert result.json()["data"]["interrupted"]
    payload = body.model_dump(mode="json")
    payload["workflow_id"] = workflow_id
    assert request("POST", "/api/v1/editorial/workflows", json=payload, headers=headers).status_code == 202
    assert editorial.read_workflow(workflow_id)["script"] == script
    assert model.call_count == 2


def test_individual_decomposition_and_script_routes_chain_the_approved_proposal(api):
    body, model, script, _ = api
    fields = body.model_dump(mode="json", exclude={"workflow_id", "target_duration_minutes"})
    headers = {"x-api-key": "test-mpt-key"}
    decomposition = request("POST", "/api/v1/editorial/decompose", json=fields, headers=headers)
    assert decomposition.status_code == 200, decomposition.text
    decision = decomposition.json()["data"]["decision"]
    assert decision["selected_id"] == 2
    generated = request("POST", "/api/v1/editorial/scripts", json={
        **fields, "decision": decision, "target_duration_minutes": 10,
    }, headers=headers)
    assert generated.status_code == 200, generated.text
    assert generated.json()["data"]["script"] == script
    assert generated.json()["data"]["selected_adaptation"]["id"] == 2
    assert model.call_count == 2


def test_queued_duplicate_is_not_scheduled_twice(api):
    body, model, _, manager = api
    manager.add_task.side_effect = None
    body.workflow_id = uuid4()
    payload = body.model_dump(mode="json")
    headers = {"x-api-key": "test-mpt-key"}
    for _ in range(2):
        result = request("POST", "/api/v1/editorial/workflows", json=payload, headers=headers)
        assert result.status_code == 202
    manager.add_task.assert_called_once()
    model.assert_not_called()


def test_workflow_cannot_overwrite_a_video_task_id(api):
    body, model, _, manager = api
    body.workflow_id = uuid4()
    editorial.sm.state.update_task(str(body.workflow_id), kind="video", progress=50)
    result = request("POST", "/api/v1/editorial/workflows", json=body.model_dump(mode="json"),
                     headers={"x-api-key": "test-mpt-key"})
    assert result.status_code == 409
    assert editorial.sm.state.get_task(str(body.workflow_id))["kind"] == "video"
    model.assert_not_called()
    manager.add_task.assert_not_called()
