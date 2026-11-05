import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import reference_research as research
from app.services import state as sm
from app.utils import utils


TEXT = (
    "Você sabe como nasceu o café? A história começa com uma descoberta. "
    "Depois, o cultivo se espalhou pelo mundo. Hoje, a bebida faz parte da rotina "
    "de muitas pessoas e cada região tem seu próprio modo de prepará-la."
)


@pytest.fixture
def reference_app(tmp_path, monkeypatch):
    report = {
        "summary": "Uma história sobre café.", "hook_analysis": "A pergunta provoca curiosidade.",
        "title_analysis": "Nenhum título foi fornecido.", "narrative_format": "Narrativa cronológica.",
        "hook_excerpt": "Você sabe como nasceu o café?", "audience": "Pessoas curiosas sobre café.",
        "structure": [
            {"name": "Introdução", "purpose": "Contextualizar", "evidence": "A história começa com uma descoberta."},
            {"name": "Expansão", "purpose": "Desenvolver", "evidence": "Depois, o cultivo se espalhou pelo mundo."},
        ],
        "pacing": "O texto avança em ordem cronológica.", "strengths": ["Pergunta clara"],
        "improvements": ["Explicar melhor o contexto"], "title_suggestions": ["Título um", "Título dois", "Título três"],
        "original_outline": ["Apresentar uma descoberta", "Explicar o processo", "Concluir com uma aplicação"],
        "script_brief": "Abra com uma pergunta e desenvolva uma sequência cronológica original.",
    }
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    monkeypatch.setattr(utils, "task_dir", lambda: str(tasks))
    monkeypatch.setattr(sm.state, "get_all_tasks", lambda *_args, **_kwargs: ([], 0))
    model = Mock(return_value=json.dumps(report))
    monkeypatch.setattr(research.llm, "_generate_response", model)
    with (
        patch.object(config, "app", dict(config.app, ollama_model_name="local-model",
                                         openai_api_key="test-key-not-real", openai_model_name="selected-model")),
        patch.object(config, "ui", dict(config.ui, language="pt")),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(Path(__file__).parents[2] / "webui/Main.py"), default_timeout=60)
        app.session_state["ui_language"] = "pt"
        app.run()
        assert not app.exception
        yield app, model, report


def test_provider_selection_is_explicit_and_does_not_trigger_a_call(reference_app):
    app, model, _ = reference_app
    assert app.radio(key="reference_analysis_provider").value == "ollama"
    app.radio(key="reference_analysis_provider").set_value("openai")
    app.run()
    assert not app.exception
    assert any("cobrança é separada" in caption.value for caption in app.caption)
    model.assert_not_called()


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_analysis_can_be_applied_without_erasing_existing_script_requirements(reference_app, provider):
    app, model, report = reference_app
    app.session_state["video_script_prompt"] = "Use um tom amigável."
    app.radio(key="reference_analysis_provider").set_value(provider)
    app.text_area(key="reference_transcript").set_value(TEXT)
    app.button(key="analyze_reference").click()
    app.run()
    assert not app.exception
    assert model.call_count == 1
    assert model.call_args.kwargs["app_config"]["llm_provider"] == provider
    assert any("Título três" in markdown.value for markdown in app.markdown)
    app.button(key="use_reference_brief").click()
    app.run()
    assert not app.exception
    assert app.session_state["video_script_prompt"] == "Use um tom amigável.\n\n" + report["script_brief"]
    assert model.call_count == 1
    app.button(key="use_reference_brief").click()
    app.run()
    assert app.session_state["video_script_prompt"].count(report["script_brief"]) == 1


def test_changed_reference_hides_stale_apply_action(reference_app):
    app, model, _ = reference_app
    app.text_area(key="reference_transcript").set_value(TEXT)
    app.button(key="analyze_reference").click()
    app.run()
    assert app.button(key="use_reference_brief")
    app.text_area(key="reference_transcript").set_value(TEXT + " Um novo trecho.")
    app.run()
    assert not app.exception
    assert not any(button.key == "use_reference_brief" for button in app.button)
    assert model.call_count == 1


def test_failed_provider_is_shown_as_an_error_without_fallback(reference_app):
    app, model, _ = reference_app
    model.return_value = "Error: provider unavailable"
    app.text_area(key="reference_transcript").set_value(TEXT)
    app.button(key="analyze_reference").click()
    app.run()
    assert not app.exception
    assert any("não retornou uma análise" in error.value for error in app.error)
    assert not any(button.key == "use_reference_brief" for button in app.button)
    assert model.call_count == 1
