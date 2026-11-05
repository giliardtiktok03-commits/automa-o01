import copy
import json
from uuid import uuid4
from unittest.mock import Mock

import pytest
from filelock import FileLock
from pydantic import ValidationError

from app.models import const
from app.models.editorial import EditorialDecision, WorkflowRequest
from app.services import editorial
from app.services.state import MemoryState


@pytest.fixture
def workflow_data():
    return {
        "reference": {"title": "Como o café chegou ao Brasil", "url": "https://youtu.be/abcdefghijk",
                      "transcript": "Uma descoberta mudou a história do café. A produção cresceu e ganhou novos caminhos. " * 2},
        "nexlev": {"source": "nexlev", "observed_at": "2026-11-05T10:00:00Z",
                   "notes": "Resultados obtidos pela automação do usuário.",
                   "videos": [{"title": "Como o café chegou ao Brasil", "url": "https://www.youtube.com/watch?v=abcdefghijk",
                               "views": 12000, "channel_median_views": 1000},
                              {"title": "Outro vídeo", "views": 500}],
                   "demand": [{"keyword": "história do café", "search_volume": 2000, "period": "monthly", "region": "BR"}],
                   "recurring_patterns": ["Histórias com uma descoberta inicial"]},
        "provider": "ollama", "target_topic": "A história do café brasileiro",
        "requirements": "Tom acessível, sem promessas exageradas.", "target_duration_minutes": 10,
    }


@pytest.fixture
def decision_data():
    return {
        "theme": "História do café", "angle": "Origem histórica", "format": "Explicação", "promise": "Entender a origem",
        "adaptations": [{"id": i, "title": f"Uma nova história {i}", "theme": "Café brasileiro",
                         "angle": f"Perspectiva original {i}", "format": f"Formato {i}",
                         "promise": f"Descobrir o aspecto {i}", "research_fit": "Considera os dados fornecidos.",
                         "originality": f"Muda a perspectiva para o aspecto {i}.", "score": score,
                         "outline": ["Gancho concreto", f"Desenvolver o aspecto {i}", "Concluir a promessa"]}
                        for i, score in [(1, 70), (2, 90), (3, 80)]],
        "selected_id": 2, "selection_reason": "Maior adequação à pesquisa e originalidade.",
    }


@pytest.fixture
def setup(tmp_path, monkeypatch, workflow_data, decision_data):
    def storage(sub_dir="", create=False):
        path = tmp_path / sub_dir
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return str(path)

    monkeypatch.setattr(editorial.utils, "storage_dir", storage)
    monkeypatch.setattr(editorial.sm, "state", MemoryState())
    monkeypatch.setattr(editorial.config, "app", {
        "ollama_model_name": "local-test-model", "openai_api_key": "test-key-not-real", "openai_model_name": "test-model",
    })
    script = ("Uma descoberta mudou o caminho do café. Vamos conhecer essa transformação por uma perspectiva original. " * 3).strip()
    model = Mock(side_effect=[json.dumps(decision_data), script])
    monkeypatch.setattr(editorial.reference_research.llm, "_generate_response", model)
    return WorkflowRequest.model_validate(workflow_data), model, script


def test_research_computes_outliers_from_observations_and_preserves_provenance(setup):
    body, model, _ = setup
    result = editorial.research(body)
    assert result["outliers"]["videos"][0]["outlier_ratio"] == 12
    assert result["outliers"]["comparable_videos"] == 1
    assert result["demand"]["observations"][0]["search_volume"] == 2000
    assert result["source"]["independently_verified"] is False
    assert result["source"]["ingestion"] == "supplied_by_automation"
    model.assert_not_called()


def test_title_only_input_does_not_claim_to_have_watched_the_video(setup):
    body, model, _ = setup
    body.reference.transcript = ""
    result = editorial.decompose(body)
    assert result.selected_id == 2
    prompt = model.call_args.kwargs["prompt"]
    assert "title-based hypotheses" in prompt
    assert not editorial.research(body)["reference_content_available"]


def test_link_only_resolves_title_using_matching_nexlev_record(setup):
    body, _, _ = setup
    body.reference.title = ""
    body.reference.transcript = ""
    result = editorial.research(body)
    assert result["reference"]["title"] == "Como o café chegou ao Brasil"


def test_unresolved_link_does_not_trigger_an_arbitrary_web_request(setup):
    body, model, _ = setup
    body.reference.title = ""
    body.reference.transcript = ""
    body.nexlev.videos = []
    with pytest.raises(editorial.EditorialError, match="reference_link_unresolved"):
        editorial.research(body)
    model.assert_not_called()


def test_missing_measurements_remain_explicitly_unknown(setup):
    body, _, _ = setup
    body.nexlev.demand = []
    body.nexlev.videos = []
    body.nexlev.recurring_patterns = []
    result = editorial.research(body)
    assert result["outliers"]["status"] == "insufficient_data"
    assert result["demand"]["status"] == "not_provided"
    assert result["recurring_patterns"]["status"] == "not_provided"


def test_complete_workflow_chooses_three_adaptations_and_scripts_the_selected_one(setup):
    body, model, script = setup
    workflow_id = str(uuid4())
    result = editorial.start_editorial(workflow_id, body)
    assert result["state"] == const.TASK_STATE_COMPLETE
    assert len(result["decomposition"]["adaptations"]) == 3
    assert result["decomposition"]["selected_id"] == 2
    assert result["approval"] == "ai_selected"
    assert result["script"] == script
    assert result["video_params"]["video_subject"] == "Uma nova história 2"
    assert result["video_params"]["video_script"] == script
    assert result["video_params"]["long_form"]
    context = json.loads(model.call_args_list[1].kwargs["prompt"].split("INPUT JSON:\n")[1])
    assert context["selected_adaptation"]["id"] == 2
    assert context["research"]["demand"]["observations"][0]["search_volume"] == 2000
    assert context["user_requirements"] == body.requirements
    assert editorial.read_workflow(workflow_id)["script"] == script
    assert "fingerprint" not in editorial.public_result(result)
    model.reset_mock()
    editorial.start_editorial(workflow_id, body)
    model.assert_not_called()


def test_failure_in_script_generation_resumes_without_repeating_decomposition(setup, monkeypatch):
    body, model, script = setup
    first = model.side_effect
    decision_json = next(first)
    model.side_effect = [decision_json, "Error: unavailable"]
    workflow_id = str(uuid4())
    failed = editorial.start_editorial(workflow_id, body)
    assert failed["state"] == const.TASK_STATE_FAILED
    assert failed["failed_stage"] == "script"
    assert failed["decomposition"]["selected_id"] == 2
    monkeypatch.setattr(editorial.sm, "state", MemoryState())
    model.reset_mock()
    model.side_effect = [script]
    result = editorial.start_editorial(workflow_id, body)
    assert result["state"] == const.TASK_STATE_COMPLETE
    assert model.call_count == 1


def test_changed_inputs_cannot_reuse_an_existing_workflow_id(setup):
    body, model, _ = setup
    workflow_id = str(uuid4())
    editorial.start_editorial(workflow_id, body)
    model.reset_mock()
    changed = body.model_copy(update={"target_topic": "Outro tema"})
    with pytest.raises(editorial.EditorialError, match="workflow_id_conflict"):
        editorial.start_editorial(workflow_id, changed)
    model.assert_not_called()


def test_duplicate_running_workflow_does_not_start_another_model_request(setup):
    body, model, _ = setup
    workflow_id = str(uuid4())
    directory = editorial.workflow_dir(workflow_id)
    with FileLock(str(directory / "running.lock")):
        assert editorial.start_editorial(workflow_id, body) is None
    model.assert_not_called()


@pytest.mark.parametrize("change", ["missing_proposal", "duplicate_ids", "wrong_selection", "duplicate_adaptation"])
def test_invalid_decisions_are_rejected(decision_data, change):
    if change == "missing_proposal":
        decision_data["adaptations"].pop()
    elif change == "duplicate_ids":
        decision_data["adaptations"][1]["id"] = 1
    elif change == "wrong_selection":
        decision_data["selected_id"] = 1
    else:
        decision_data["adaptations"][1] = {**decision_data["adaptations"][0], "id": 2}
    with pytest.raises(ValidationError):
        EditorialDecision.model_validate(decision_data)


@pytest.mark.parametrize("change", ["empty_reference", "missing_research", "negative_views", "infinite_baseline", "credentials_url"])
def test_invalid_research_inputs_are_rejected(workflow_data, change):
    if change == "empty_reference":
        workflow_data["reference"] = {}
    elif change == "missing_research":
        workflow_data["nexlev"] = {}
    elif change == "negative_views":
        workflow_data["nexlev"]["videos"][0]["views"] = -1
    elif change == "infinite_baseline":
        workflow_data["nexlev"]["videos"][0]["channel_median_views"] = float("inf")
    else:
        workflow_data["reference"]["url"] = "https://user:password@example.com/video"
    with pytest.raises(ValidationError):
        WorkflowRequest.model_validate(workflow_data)


def test_redis_queue_round_trip_keeps_the_editorial_contract(setup):
    from app.controllers.manager.redis_manager import RedisTaskManager

    body, _, _ = setup
    body.workflow_id = uuid4()
    task = {"func": editorial.start_editorial, "args": [],
            "kwargs": {"task_id": str(body.workflow_id), "params": body}}
    original = copy.deepcopy(body)
    serialized = RedisTaskManager._serialize_task(task)
    restored = RedisTaskManager.__new__(RedisTaskManager)._deserialize_task(serialized)
    assert isinstance(restored["kwargs"]["params"], WorkflowRequest)
    assert restored["kwargs"]["params"] == original
    assert task["kwargs"]["params"] == original
    assert restored["func"] is editorial.start_editorial
