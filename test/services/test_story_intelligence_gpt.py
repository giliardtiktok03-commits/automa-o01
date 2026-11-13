"""Simulated OpenAI SDK integration and an opt-in, single-request live test."""
import json
import os
from unittest.mock import patch

import pytest
from openai.types.chat import ChatCompletion
from streamlit.testing.v1 import AppTest
from app.config import config
from app.models.story_intelligence import EpisodeBlueprint, CentralConflict, EditorialClaim
from app.services import story_intelligence as story, channel_skills as library, llm, task

TOPIC = 'Operation Gold: The Spy Tunnel Beneath Berlin'
SETTINGS = {'llm_provider': 'another-provider', 'openai_api_key': 'simulated-private-key', 'openai_model_name': 'gpt-4.1-mini'}
EVIDENCE = [{'id': 'record-1', 'title': 'Synthetic test record, not historical evidence',
             'excerpt': 'Fixture: the objective met a technical constraint.', 'interpretation': 'documented'}]


@pytest.fixture(autouse=True)
def library_local(tmp_path, monkeypatch):
    monkeypatch.setattr(library, '_root', lambda: tmp_path)
    story.install()


@pytest.fixture
def no_openai(monkeypatch):
    monkeypatch.setitem(config.app, 'openai_api_key', '')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)


def model_output(sources=None):
    bp = story.analyze(TOPIC, use_model=False, app_config={})
    bp.primary_story_engine = 'technology_vs_constraints'  # GPT's choice overrides the local keyword heuristic.
    bp.narrative_potential = 'Contrastar ambição operacional, limites técnicos e o que os documentos permitem concluir.'
    bp.reason_for_structure = 'A capacidade técnica e seus limites devem conduzir o argumento, em vez de uma cronologia genérica.'
    bp.central_conflicts = [CentralConflict(tension='Intended objective versus operational constraints', stakes='What could the operation actually establish?', source_ids=[], uncertainty='Proposed research axis; verify it in reliable records.')]
    bp.progression_strategy = 'Move from the stated objective to constraints, responses, outcomes and limits of the surviving evidence.'
    bp.ending_strategy = 'Answer what the evidence establishes and distinguish that conclusion from open questions.'
    bp.pacing_strategy = 'Use new evidence for reengagement; reduce duration if evidence does not support twenty minutes.'
    bp.claim_register = [EditorialClaim(statement='Which objective and constraint can be established?', classification='research_gap', material=True)]
    result = bp.model_dump()
    result['source_register'] = sources or []
    return result


def complete(response):
    return ChatCompletion(id='simulated', object='chat.completion', created=0, model='gpt-4.1-mini',
                          choices=[{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(response)}}])


def test_default_calls_existing_openai_adapter_with_full_context_and_no_media():
    response = model_output()
    original = dict(SETTINGS)
    with patch.object(llm, 'OpenAI') as client, patch.object(task, 'start') as start:
        client.return_value.chat.completions.create.return_value = complete(response)
        bp = story.analyze(TOPIC, sources=EVIDENCE, app_config=SETTINGS)
        create = client.return_value.chat.completions.create
        assert create.call_count == 1
        request = create.call_args.kwargs
        prompt = request['messages'][0]['content']
        assert request['model'] == 'gpt-4.1-mini'
        assert all(value in prompt for value in [TOPIC, 'bta-001', 'bta-002', 'bta-003', '20', 'record-1', EVIDENCE[0]['excerpt'], 'measured documentary delivery'])
        assert 'simulated-private-key' not in prompt
        assert 'Every factual assertion' in prompt
        # No generic local blueprint is proposed as an answer to the director.
        raw = prompt.split('A human will edit, review evidence and approve this plan separately.\n', 1)[1]
        context = json.loads(raw)
        assert 'blueprint' not in context and 'primary_story_engine' not in context['request']
        assert bp.primary_story_engine == 'technology_vs_constraints'
        assert bp.analysis_method == 'central_model'
        assert bp.analysis_provider == 'openai' and bp.analysis_model == 'gpt-4.1-mini'
        assert bp.fallback_reason == ''
        assert bp.readiness == 'research_required' and not bp.approved_for_script
        assert bp.source_register[0].excerpt == EVIDENCE[0]['excerpt']
        assert client.call_args.kwargs['timeout'] == 120.0
        assert client.call_args.kwargs['max_retries'] == 0
        start.assert_not_called()
    assert SETTINGS == original  # No switch to the application's global provider.


def test_unconfigured_auto_is_clearly_simplified_and_does_not_call_model(no_openai):
    with patch.object(llm, '_generate_response') as call:
        bp = story.analyze(TOPIC, app_config={})
        assert bp.analysis_method == 'local_provisional' and bp.fallback_reason == 'not_configured'
        assert 'Análise local simplificada' in story.report(bp)
        call.assert_not_called()


def test_selected_local_stays_local_even_with_openai_configured():
    with patch.object(llm, '_generate_response') as call:
        bp = story.analyze(TOPIC, use_model=False, app_config=SETTINGS)
        assert bp.fallback_reason == 'selected_local'
        call.assert_not_called()


@pytest.mark.parametrize('reply,reason', [('Error: simulated connection failure', 'api_unavailable'), ('', 'api_unavailable'), ('not JSON', 'invalid_response')])
def test_model_failure_never_silently_disguises_local_as_gpt(reply, reason):
    with patch.object(llm, '_generate_response', return_value=reply) as call:
        with pytest.raises(story.StoryModelUnavailable) as failed:
            story.analyze(TOPIC, app_config=SETTINGS)
        assert failed.value.reason == reason
        assert call.call_count == 1
        local = story.analyze(TOPIC, use_model=False, fallback_reason=reason, app_config=SETTINGS)
        assert local.analysis_method == 'local_provisional' and local.fallback_reason == reason
        assert call.call_count == 1


def test_claims_distinguish_facts_allegations_inferences_and_gaps():
    data = model_output(EVIDENCE)
    quote = {'source_id': 'record-1', 'excerpt': 'the objective met a technical constraint'}
    data['claim_register'] = [
        {'statement': 'Fixture: an objective met a constraint.', 'classification': 'documented_fact', 'source_ids': ['record-1'], 'evidence_quotes': [quote]},
        {'statement': 'An attributed fixture allegation.', 'classification': 'allegation', 'source_ids': ['record-1'], 'evidence_quotes': [quote], 'caveat': 'Attributed allegation, not independently established.'},
        {'statement': 'A tentative inference about a fixture constraint.', 'classification': 'inference', 'source_ids': ['record-1'], 'evidence_quotes': [quote], 'caveat': 'Interpretation of the supplied record, not a proven motive.'},
        {'statement': 'An unresearched central question.', 'classification': 'research_gap'},
        {'statement': 'Unsupported assertion must not be accepted as fact.', 'classification': 'documented_fact', 'source_ids': ['invented-record'], 'evidence_quotes': [{'source_id': 'invented-record', 'excerpt': 'fabricated'}]},
    ]
    data['approved_for_script'] = data['evidence_reviewed'] = True
    data['readiness'] = 'ready_to_write'
    with patch.object(llm, '_generate_response', return_value=json.dumps(data)):
        bp = story.analyze(TOPIC, sources=EVIDENCE, app_config=SETTINGS)
    assert [claim.classification for claim in bp.claim_register] == ['documented_fact', 'allegation', 'inference', 'research_gap', 'research_gap']
    assert bp.claim_register[-1].source_ids == [] and bp.claim_register[-1].evidence_quotes == []
    assert not bp.approved_for_script and not bp.evidence_reviewed
    assert bp.readiness == 'research_required'
    assert len(bp.source_register) == 1


def test_wrong_quote_is_a_research_gap_even_when_the_source_id_exists():
    data = model_output(EVIDENCE)
    data['claim_register'] = [{'statement': 'An invented result.', 'classification': 'documented_fact', 'source_ids': ['record-1'], 'evidence_quotes': [{'source_id': 'record-1', 'excerpt': 'This quote is not in the record.'}]}]
    with patch.object(llm, '_generate_response', return_value=json.dumps(data)):
        bp = story.analyze(TOPIC, sources=EVIDENCE, app_config=SETTINGS)
    assert bp.claim_register[0].classification == 'research_gap'
    assert bp.claim_register[0].evidence_quotes == []


def test_old_saved_blueprints_remain_valid():
    value = model_output()
    for name in ['analysis_revision', 'analysis_provider', 'analysis_model', 'fallback_reason', 'narrative_potential', 'central_conflicts', 'progression_strategy', 'ending_strategy', 'pacing_strategy', 'claim_register']:
        value.pop(name, None)
    old = EpisodeBlueprint.model_validate(value)
    assert old.analysis_revision == 1
    identifier = story.save_blueprint(old)
    assert story.load_blueprint(identifier).analysis_revision == 1


UI = '''
import streamlit as st
from app.models.schema import VideoParams
from webui.channel_skills import render
params = VideoParams(video_subject='Operation Gold')
render(st.container(), params, lambda *args:None, lambda *args:None)
'''


def open_ui():
    app = AppTest.from_string(UI).run()
    app.checkbox(key='channel_skills_enabled').check().run()
    app.multiselect(key='channel_skill_ids').select(story.SKILL_ID).run()
    app.text_input(key='bta_topic').set_value(TOPIC).run()
    return app


def test_ui_default_is_gpt_and_analysis_only():
    response = model_output()
    with patch.dict(config.app, SETTINGS), patch.dict(config.ui, {}, clear=True), patch.object(llm, '_generate_response', return_value=json.dumps(response)) as call, patch.object(task, 'start') as start:
        app = open_ui()
        assert not app.exception
        assert app.selectbox(key='bta_analysis_mode_v2').value.startswith('Automático')
        app.button(key='bta_analyze').click().run()
        assert not app.exception
        assert app.session_state['bta_blueprint']['analysis_method'] == 'central_model'
        assert any('GPT / OpenAI' in item.value for item in app.success)
        assert not app.session_state['bta_blueprint']['approved_for_script']
        assert app.button(key='bta_approve').disabled
        assert call.call_count == 1
        start.assert_not_called()


def test_ui_explicit_fallback_does_not_submit_a_second_api_request():
    with patch.dict(config.app, SETTINGS), patch.dict(config.ui, {}, clear=True), patch.object(llm, '_generate_response', return_value='Error: unavailable') as call:
        app = open_ui()
        app.button(key='bta_analyze').click().run()
        assert not app.exception
        assert app.button(key='bta_local_fallback')
        app.button(key='bta_local_fallback').click().run()
        assert not app.exception
        assert app.session_state['bta_blueprint']['analysis_method'] == 'local_provisional'
        assert app.session_state['bta_blueprint']['fallback_reason'] == 'api_unavailable'
        assert any('ANÁLISE LOCAL SIMPLIFICADA' in item.value for item in app.warning)
        assert call.call_count == 1


def test_live_openai_director_when_configured():
    if os.environ.get('MPT_STORY_LIVE_TESTS') != '1':
        pytest.skip('Real API test is opt-in to avoid paid requests in ordinary regression runs')
    settings = story.openai_settings()
    if not story.model_status(settings)['configured']:
        pytest.skip('OpenAI key/model not configured; no real API request sent')
    bp = story.analyze(TOPIC, duration=5, use_model=True, app_config=settings)
    assert bp.analysis_method == 'central_model'
    assert bp.narrative_potential and bp.central_conflicts and bp.progression_strategy and bp.ending_strategy and bp.claim_register
    assert bp.source_register == []
    assert not bp.approved_for_script and bp.readiness != 'ready_to_write'
    assert all(claim.classification == 'research_gap' for claim in bp.claim_register)


def test_complete_gpt_plan_requires_manual_review_before_script_approval():
    data = model_output(EVIDENCE)
    data['claim_register'] = [{'statement': 'Fixture objective versus constraint.', 'classification': 'documented_fact', 'source_ids': ['record-1'], 'evidence_quotes': [{'source_id': 'record-1', 'excerpt': EVIDENCE[0]['excerpt']}]}]
    for beat in data['narrative_beats']:
        beat['source_ids'] = ['record-1']
        beat['confidence'] = 'verified'
    data['approved_for_script'] = data['evidence_reviewed'] = True
    data['readiness'] = 'ready_to_write'
    with patch.object(llm, '_generate_response', return_value=json.dumps(data)):
        bp = story.analyze(TOPIC, sources=EVIDENCE, app_config=SETTINGS)
    assert not bp.approved_for_script and bp.readiness == 'research_required'
    assert all(beat.confidence == 'needs_research' for beat in bp.narrative_beats)
    # Human changes confidence only after comparing each beat with the sources.
    for beat in bp.narrative_beats:
        beat.confidence = 'verified'
    approved = story.approve(bp, evidence_reviewed=True)
    assert approved.approved_for_script
    identifier = story.save_blueprint(approved)
    restored = story.load_blueprint(identifier)
    assert restored.analysis_model == 'gpt-4.1-mini'
    assert restored.claim_register[0].evidence_quotes[0].excerpt == EVIDENCE[0]['excerpt']


def test_sdk_exception_does_not_leak_details_or_retry():
    with patch.object(llm, '_generate_response', side_effect=RuntimeError('sensitive-provider-details')) as call:
        with pytest.raises(story.StoryModelUnavailable) as failed:
            story.analyze(TOPIC, app_config=SETTINGS)
        assert 'sensitive-provider-details' not in str(failed.value)
        assert call.call_count == 1


@pytest.mark.parametrize('provider',['openai_codex','openai_chatgpt'])
def test_explicit_autopilot_login_blueprint_uses_existing_oauth_adapter(provider,monkeypatch):
    from unittest.mock import Mock
    from app.services import codex_oauth,chatgpt_oauth
    monkeypatch.setattr(codex_oauth,'account_status',lambda:True)
    monkeypatch.setattr(chatgpt_oauth,'account_status',lambda:True)
    output=model_output()
    selected=codex_oauth if provider=='openai_codex' else chatgpt_oauth
    generate=Mock(return_value=json.dumps(output));monkeypatch.setattr(selected,'generate_text',generate)
    paid=Mock(side_effect=AssertionError('No OpenAI API key in login mode'));monkeypatch.setattr(llm,'OpenAI',paid)
    bp=story.analyze(TOPIC,use_model=True,use_selected_provider=True,
        app_config={'llm_provider':provider,provider+'_model_name':'configured-model','openai_api_key':''})
    assert bp.analysis_provider==provider and bp.analysis_model=='configured-model'
    assert generate.call_count==1
    paid.assert_not_called()


def test_explicit_public_coarena_blueprint_preserves_model_and_source_guards(monkeypatch):
    from unittest.mock import Mock
    output=model_output()
    generate=Mock(return_value=json.dumps(output));monkeypatch.setattr(llm,'_generate_response',generate)
    bp=story.analyze(TOPIC,use_model=True,use_selected_provider=True,app_config={
        'llm_provider':'coarena','coarena_api_key':'simulated-key','coarena_model_name':'claude-fable-5'})
    assert bp.analysis_provider=='coarena' and bp.analysis_model=='claude-fable-5'
    assert not bp.approved_for_script and not bp.evidence_reviewed
    assert generate.call_args.kwargs['app_config']['llm_provider']=='coarena'
    assert generate.call_args.kwargs['max_retries']==0
