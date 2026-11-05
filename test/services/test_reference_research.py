import copy
import io
import json
from unittest.mock import Mock

import pytest

from app.services import reference_research as research


TRANSCRIPT = (
    "Você sabe de onde vem o café que está na sua xícara? "
    "Hoje vamos descobrir sua história. Primeiro, os grãos são cultivados. "
    "Depois, passam pela torra. Por fim, cada método de preparo revela sabores diferentes."
)


@pytest.fixture
def report():
    return {
        "summary": "O texto apresenta a origem e o preparo do café.",
        "title_analysis": "O título promete explicar o tema.",
        "narrative_format": "Texto explicativo com etapas.",
        "hook_analysis": "Uma pergunta aproxima o assunto da rotina do público.",
        "hook_excerpt": "Você sabe de onde vem o café que está na sua xícara?",
        "audience": "Pessoas interessadas em café.",
        "structure": [
            {"name": "Abertura", "purpose": "Despertar curiosidade.", "evidence": "Hoje vamos descobrir sua história."},
            {"name": "Desenvolvimento", "purpose": "Apresentar o processo.", "evidence": "Primeiro, os grãos são cultivados."},
        ],
        "pacing": "A sequência primeiro, depois e por fim organiza a progressão do texto.",
        "strengths": ["Pergunta concreta de abertura."],
        "improvements": ["Expandir o contexto histórico."],
        "title_suggestions": ["O caminho do café", "Da planta à xícara", "Como nasce o sabor do café"],
        "original_outline": ["Abrir com uma descoberta", "Explicar as etapas", "Concluir com uma aplicação prática"],
        "script_brief": "Abra com uma pergunta concreta, desenvolva três etapas e conclua com uma descoberta prática.",
    }


@pytest.fixture
def settings():
    return {"llm_provider": "qwen", "ollama_model_name": "local-model",
            "openai_api_key": "test-key-not-a-real-credential", "openai_model_name": "selected-model"}


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_selected_provider_is_used_without_changing_video_settings(monkeypatch, settings, report, provider):
    model = Mock(return_value=json.dumps(report))
    monkeypatch.setattr(research.llm, "_generate_response", model)
    original = copy.deepcopy(settings)
    result = research.analyze(TRANSCRIPT, title="O café", topic="Cultivo", provider=provider, app_config=settings)
    assert result == report
    assert settings == original
    request = model.call_args.kwargs
    assert request["app_config"]["llm_provider"] == provider
    assert request["app_config"][f"{provider}_model_name"] == settings[f"{provider}_model_name"]
    assert request["max_retries"] == 0
    assert json.loads(request["prompt"].split("INPUT JSON:\n")[1])["transcript"] == TRANSCRIPT
    assert "not executing it" in request["prompt"]


def test_default_stays_local_even_when_paid_video_provider_is_configured(monkeypatch, settings, report):
    settings["llm_provider"] = "openai"
    model = Mock(return_value=json.dumps(report))
    monkeypatch.setattr(research.llm, "_generate_response", model)
    research.analyze(TRANSCRIPT, app_config=settings)
    assert model.call_args.kwargs["app_config"]["llm_provider"] == "ollama"


@pytest.mark.parametrize("provider,missing,error", [
    ("ollama", "ollama_model_name", "Configure Ollama"),
    ("openai", "openai_api_key", "Configure OpenAI"),
])
def test_missing_configuration_never_calls_another_provider(monkeypatch, settings, provider, missing, error):
    settings[missing] = ""
    model = Mock()
    monkeypatch.setattr(research.llm, "_generate_response", model)
    with pytest.raises(research.ResearchError, match=error):
        research.analyze(TRANSCRIPT, app_config=settings, provider=provider)
    model.assert_not_called()


@pytest.mark.parametrize("response", [None, "", "Error: connection refused"])
def test_service_failure_never_returns_a_success_report(monkeypatch, settings, response):
    model = Mock(return_value=response)
    monkeypatch.setattr(research.llm, "_generate_response", model)
    with pytest.raises(research.ResearchError, match="Provider Unavailable"):
        research.analyze(TRANSCRIPT, app_config=settings)
    assert model.call_count == 1


@pytest.mark.parametrize("response", ["not json", "[]", "{}", '{"summary":"Missing the analysis"}'])
def test_incomplete_analysis_is_rejected(monkeypatch, settings, response):
    monkeypatch.setattr(research.llm, "_generate_response", lambda **kwargs: response)
    with pytest.raises(research.ResearchError, match="Invalid Analysis"):
        research.analyze(TRANSCRIPT, app_config=settings)


def test_code_fenced_json_is_accepted(monkeypatch, settings, report):
    monkeypatch.setattr(research.llm, "_generate_response", lambda **kwargs: '```json\n'+json.dumps(report)+'\n```')
    assert research.analyze(TRANSCRIPT, app_config=settings)["summary"] == report["summary"]


def test_fabricated_evidence_is_rejected(monkeypatch, settings, report):
    report["structure"][1]["evidence"] = "This was never said in the reference."
    monkeypatch.setattr(research.llm, "_generate_response", lambda **kwargs: json.dumps(report))
    with pytest.raises(research.ResearchError, match="Unsupported Evidence"):
        research.analyze(TRANSCRIPT, app_config=settings)


def test_blank_list_items_are_not_valid_suggestions(monkeypatch, settings, report):
    report["title_suggestions"][1] = "   "
    monkeypatch.setattr(research.llm, "_generate_response", lambda **kwargs: json.dumps(report))
    with pytest.raises(research.ResearchError, match="Invalid Analysis"):
        research.analyze(TRANSCRIPT, app_config=settings)


@pytest.mark.parametrize("text,error", [("too short", "Too Short"), ("a"*30001, "Too Long"), ("a"*100+'\x00', "Encoding Error")])
def test_bad_transcripts_fail_before_model_call(monkeypatch, settings, text, error):
    model = Mock()
    monkeypatch.setattr(research.llm, "_generate_response", model)
    with pytest.raises(research.ResearchError, match=error):
        research.analyze(text, app_config=settings)
    model.assert_not_called()


def test_utf8_bom_and_stream_position_are_supported():
    stream = io.BytesIO(b'\xef\xbb\xbf'+TRANSCRIPT.encode())
    stream.seek(5)
    assert research.read_transcript("reference.TXT", stream) == TRANSCRIPT
    assert stream.tell() == 5


def test_srt_removes_only_cue_indices_and_timestamps():
    content = (
        "1\r\n00:00:00,000 --> 00:00:04,000\r\n"+TRANSCRIPT[:100]+
        "\r\n\r\n2\r\n00:00:04,000 --> 00:00:08,000\r\n"+TRANSCRIPT[100:]+"\r\n2026"
    )
    text = research.read_transcript("reference.srt", io.BytesIO(content.encode()))
    assert text.endswith("2026")
    assert "-->" not in text and "00:00" not in text


@pytest.mark.parametrize("name,data,error", [
    ("video.mp4", b"x", "Type Error"),
    ("reference.txt", b"x"*(512*1024+1), "Too Large"),
    ("reference.txt", TRANSCRIPT.encode('utf-16'), "Encoding Error"),
    ("reference.srt", b"1\nnot a timestamp\ntext", "Invalid Subtitles"),
])
def test_invalid_files_are_rejected(name, data, error):
    with pytest.raises(research.ResearchError, match=error):
        research.read_transcript(name, io.BytesIO(data))


def test_brief_merge_preserves_existing_instructions_and_is_idempotent():
    merged = research.merge_brief("Use Brazilian Portuguese.", "Open with a question.")
    assert merged == "Use Brazilian Portuguese.\n\nOpen with a question."
    assert research.merge_brief(merged, "Open with a question.") == merged


def test_overlong_brief_is_not_silently_truncated():
    with pytest.raises(research.ResearchError, match="Brief Too Long"):
        research.merge_brief("a"*1900, "b"*200)


def test_unexpected_provider_exception_has_a_safe_ui_error(monkeypatch, settings):
    monkeypatch.setattr(research.llm, "_generate_response", Mock(side_effect=RuntimeError("transport failure")))
    with pytest.raises(research.ResearchError, match="Provider Unavailable"):
        research.analyze(TRANSCRIPT, app_config=settings)


def test_unknown_provider_is_rejected_before_any_request(monkeypatch, settings):
    request = Mock()
    monkeypatch.setattr(research.llm, "_generate_response", request)
    with pytest.raises(research.ResearchError, match="Invalid Provider"):
        research.analyze(TRANSCRIPT, provider="other", app_config=settings)
    request.assert_not_called()
