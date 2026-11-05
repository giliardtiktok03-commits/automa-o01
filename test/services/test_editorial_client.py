from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
import requests

from scripts import editorial_pipeline as client


def response(data):
    result = Mock()
    result.json.return_value = {"data": data}
    return result


def test_python_client_submits_once_and_polls_without_following_external_status_urls(monkeypatch):
    workflow_id = str(uuid4())
    session = MagicMock()
    session.__enter__.return_value = session
    session.post.return_value = response({"workflow_id": workflow_id, "status_url": "https://unrelated.invalid/"})
    completed = {"workflow_id": workflow_id, "state": 1, "script": "An original script"}
    session.get.side_effect = [response({"state": 4}), response(completed)]
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    monkeypatch.setattr(client.time, "sleep", Mock())
    result = client.run_workflow("https://mpt.example.test/", {"workflow_id": workflow_id}, api_key="test-key")
    assert result == completed
    session.post.assert_called_once()
    assert session.post.call_args.kwargs["headers"] == {"x-api-key": "test-key"}
    assert session.get.call_count == 2
    assert session.get.call_args.args[0] == f"https://mpt.example.test/api/v1/editorial/workflows/{workflow_id}"


def test_timeout_does_not_automatically_repeat_a_model_workflow(monkeypatch):
    session = MagicMock()
    session.__enter__.return_value = session
    session.post.side_effect = requests.Timeout("submission timeout")
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    with pytest.raises(requests.Timeout):
        client.run_workflow("http://mpt.example.test", {"workflow_id": str(uuid4())})
    session.post.assert_called_once()
    session.get.assert_not_called()


def test_failed_workflow_has_an_actionable_error(monkeypatch):
    workflow_id = str(uuid4())
    session = MagicMock()
    session.__enter__.return_value = session
    session.post.return_value = response({"workflow_id": workflow_id})
    session.get.return_value = response({"state": -1, "failed_stage": "script", "error": "Reference Provider Unavailable"})
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    with pytest.raises(RuntimeError, match="failed at script"):
        client.run_workflow("http://mpt.example.test", {"workflow_id": workflow_id})


def test_client_requires_a_stable_uuid_before_connecting(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(client.requests, "Session", factory)
    with pytest.raises(ValueError):
        client.run_workflow("http://mpt.example.test", {"workflow_id": "not-a-uuid"})
    factory.assert_not_called()
