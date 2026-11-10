import json
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest
from app.config import config
from app.models.schema import VideoParams
from app.services import channel_skills as library, channel_skill_runtime as runtime, story_intelligence as story, llm, task, long_form


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(library, '_root', lambda: tmp_path)
    story.install()
    return tmp_path


def supported():
    bp = story.analyze('Operation Gold: The Spy Tunnel Beneath Berlin')
    bp.source_register = [story.Source(id='record-1', title='User-supplied record', excerpt='Test fixture excerpt, not historical research.', interpretation='documented')]
    for beat in bp.narrative_beats:
        beat.source_ids = ['record-1']
        beat.confidence = 'verified'
    return bp


@pytest.mark.parametrize('topic,expected,match', [
    ('The ENTIRE History of the GRU in 20 Minutes', 'duplicate', 'bta-001'),
    ("Project Azorian: The CIA's Mining Ship", 'duplicate', 'bta-002'),
    ('The US Planned to Hide Nuclear Missiles Beneath Greenland’s Ice', 'duplicate', 'bta-003'),
    ('Glomar Explorer', 'duplicate', 'bta-002'),
    ('A Specific GRU Operation Not Covered in the Published GRU Episode', 'overlap_requires_distinct_angle', 'bta-001'),
    ('Operation Gold: The Spy Tunnel Beneath Berlin', 'new', None),
])
def test_acceptance_novelty(topic, expected, match):
    bp = story.analyze(topic)
    assert bp.editorial_memory_check.status == expected
    if match:
        assert match in bp.editorial_memory_check.matched_video_ids
    assert not bp.approved_for_script


def test_inventory_metadata_unknown_and_bootstrap_never_overwrites(local):
    value = story.memory()
    assert len(value['videos']) == 3
    assert all(row['status'] == 'published' and row['youtube_url'] is None and row['performance_metrics'] is None for row in value['videos'])
    value['videos'][0]['title'] = 'User-edited title'
    story.save_memory(value)
    library.save(story.SKILL_ID, b'User-edited skill', replace=True)
    story.install()
    assert library.load(story.SKILL_ID).content == 'User-edited skill'
    assert story.memory()['videos'][0]['title'] == 'User-edited title'
    library.remove(story.SKILL_ID)
    story.install()
    assert not library.installed()  # Bootstrap does not undo explicit archiving.


def test_planning_is_independent_and_unsourced_never_ready():
    with patch.object(task, 'start') as start, patch.object(task, 'generate_audio') as audio, patch.object(llm, '_generate_response') as call:
        bp = story.analyze('Operation Gold: The Spy Tunnel Beneath Berlin')
        assert bp.primary_story_engine == 'covert_mission'
        assert bp.readiness == 'research_required'
        assert bp.source_register == []
        assert len(bp.narrative_beats) == 5
        assert bp.temporal_window == bp.geography == 'unknown'
        with pytest.raises(story.StoryError):
            story.approve(bp, evidence_reviewed=True)
        start.assert_not_called()
        audio.assert_not_called()
        call.assert_not_called()


def test_central_model_cannot_invent_evidence_or_approve_itself():
    fake = supported()
    fake.source_register[0].url = 'https://invented.invalid/record'
    fake.approved_for_script = True
    fake.evidence_reviewed = True
    fake.readiness = 'ready_to_write'
    with patch.object(llm, '_generate_response', return_value=fake.model_dump_json()) as call:
        bp = story.analyze(fake.input_topic, use_model=True, app_config={'llm_provider': 'openai', 'openai_api_key': 'not-real'})
        assert call.call_count == 1
        assert bp.source_register == []
        assert bp.readiness == 'research_required'
        assert not bp.approved_for_script
        assert all(beat.confidence == 'needs_research' for beat in bp.narrative_beats)
        assert 'not-real' not in call.call_args.args[0]


def test_duplicate_never_calls_model():
    with patch.object(llm, '_generate_response') as call:
        bp = story.analyze('Project Azorian', use_model=True)
        assert bp.readiness == 'needs_revision'
        call.assert_not_called()


def test_review_keeps_disputes_and_requires_explicit_evidence_review():
    bp = supported()
    bp.source_register.append(story.Source(id='record-2', title='Conflicting interpretation', excerpt='Different account.', interpretation='disputed'))
    bp.narrative_beats[0].source_ids.append('record-2')
    with pytest.raises(story.StoryError):
        story.approve(bp)
    approved = story.approve(bp, evidence_reviewed=True)
    assert approved.approved_for_script
    assert approved.narrative_beats[0].confidence == 'supported_but_disputed'
    assert any('Competing' in flag for flag in approved.risk_flags)
    assert len(approved.source_register) == 2


def test_revision_and_library_status_never_publish(local):
    bp = story.analyze('Operation Gold')
    identifier = story.save_blueprint(bp, status='planned')
    story.save_blueprint(bp, episode_id=identifier, status='in_production')
    assert len(list((local/story.SKILL_ID/'blueprints'/identifier).glob('revision-*.json'))) == 2
    assert story.load_blueprint(identifier).input_topic == 'Operation Gold'
    row = next(row for row in story.memory()['videos'] if row['id'] == identifier)
    assert row['status'] == 'in_production' and row['published_at'] is None
    with pytest.raises(story.StoryError):
        story.save_blueprint(bp, status='published')
    with pytest.raises(story.StoryError):
        story.load_blueprint('../escape')


def test_approved_context_is_frozen_and_topic_specific():
    bp = story.approve(supported(), evidence_reviewed=True)
    params = VideoParams(video_subject=bp.input_topic, skills_enabled=True, skill_ids=[story.SKILL_ID], voice_name='approved-voice')
    runtime.freeze(params)
    story.bind(params, bp)
    runtime.freeze(params)
    with runtime.scope(params.skill_snapshot):
        runtime.require_script_ready(bp.input_topic)
        prompt = runtime.decorate('Write narration')
        assert story.MARKER.strip() in prompt
        assert 'record-1' in prompt
        with pytest.raises(story.StoryError):
            runtime.require_script_ready('A different topic')
    library.remove(story.SKILL_ID)
    # Submitted snapshots survive edits/removal of the installed skill.
    with runtime.scope(params.skill_snapshot):
        runtime.require_script_ready(bp.input_topic)
    assert params.voice_name == 'approved-voice'


def test_missing_blueprint_blocks_model_but_disabled_skill_does_not():
    params = VideoParams(video_subject='Operation Gold', skills_enabled=True, skill_ids=[story.SKILL_ID])
    runtime.freeze(params)
    with patch.object(llm, '_generate_response', return_value='Narration') as call:
        with runtime.scope(params.skill_snapshot):
            assert llm.generate_script(params.video_subject) == ''
        call.assert_not_called()
        with runtime.scope([]):
            assert llm.generate_script(params.video_subject) == 'Narration'
        assert call.call_count == 1


def test_memory_change_invalidates_new_binding():
    bp = story.approve(supported(), evidence_reviewed=True)
    params = VideoParams(video_subject=bp.input_topic, skills_enabled=True, skill_ids=[story.SKILL_ID])
    runtime.freeze(params)
    inventory = story.memory()
    inventory['notes'] += ' Revision.'
    story.save_memory(inventory)
    with pytest.raises(story.StoryError, match='memória editorial mudou'):
        story.bind(params, bp)


UI = '''
import streamlit as st
from app.models.schema import VideoParams
from webui.channel_skills import render
params = VideoParams(video_subject='Operation Gold')
def save(section, key, value): pass
def heading(number, label, color): st.markdown(f'{number:02d} · {label}')
render(st.container(), params, save, heading)
st.session_state['captured']=params.model_dump(mode='json')
'''


def test_existing_skills_ui_analyzes_and_saves_without_media():
    with patch.dict(config.ui, {}, clear=True), patch.object(task, 'start') as start, patch.object(llm, '_generate_response') as model:
        app = AppTest.from_string(UI).run()
        assert not app.exception
        assert not app.checkbox(key='channel_skills_enabled').value
        assert len(app.button) > 0
        app.checkbox(key='channel_skills_enabled').check().run()
        app.multiselect(key='channel_skill_ids').select(story.SKILL_ID).run()
        app.text_input(key='bta_topic').set_value('Operation Gold').run()
        app.button(key='bta_analyze').click().run()
        assert not app.exception
        assert app.session_state['bta_blueprint']['readiness'] == 'research_required'
        assert app.button(key='bta_approve').disabled
        app.button(key='bta_save').click().run()
        assert not app.exception
        assert len(story.saved_blueprints()) == 1
        start.assert_not_called()
        model.assert_not_called()


def test_saved_production_episode_does_not_duplicate_itself():
    identifier = story.save_blueprint(supported(), status='in_production')
    bp = story.load_blueprint(identifier)
    approved = story.approve(bp, evidence_reviewed=True)
    assert approved.readiness == 'ready_to_write'
    assert approved.editorial_id == identifier
    # A different project with the same event remains a duplicate.
    assert story.analyze(bp.input_topic).editorial_memory_check.status == 'duplicate'


def test_distinct_perspective_requires_concrete_angle_and_confirmation():
    bp = supported()
    bp.input_topic = 'A GRU Operation With a Specific Central Question'
    assert story.review(bp, evidence_reviewed=True, distinct_angle_reviewed=True).readiness == 'needs_revision'
    bp.distinct_angle = 'Investigate a specific operation and its independently documented decision chain, rather than repeating the institution history.'
    assert story.review(bp, evidence_reviewed=True).readiness == 'needs_revision'
    assert story.approve(bp, evidence_reviewed=True, distinct_angle_reviewed=True).readiness == 'ready_to_write'


def test_forged_ready_flag_does_not_send_unverified_plan_to_script():
    bp = story.analyze('Operation Gold')
    bp.approved_for_script = True
    bp.evidence_reviewed = True
    bp.readiness = 'ready_to_write'
    params = VideoParams(video_subject=bp.input_topic, skills_enabled=True, skill_ids=[story.SKILL_ID])
    runtime.freeze(params)
    with pytest.raises(story.StoryError, match='suporte'):
        story.bind(params, bp)


def test_approved_blueprint_reaches_existing_text_model_and_chapter_writer():
    bp = story.approve(supported(), evidence_reviewed=True)
    params = VideoParams(video_subject=bp.input_topic, skills_enabled=True, skill_ids=[story.SKILL_ID])
    runtime.freeze(params)
    story.bind(params, bp)
    with runtime.scope(params.skill_snapshot), patch.object(llm, '_generate_response', return_value='Narration') as call:
        assert llm.generate_script(params.video_subject) == 'Narration'
        assert long_form._script(params, [{'title': 'Operational question'}], 0) == 'Narration'
        assert call.call_count == 2
    # Existing JSON provider snapshot used in the WebUI is also checked.
    cfg = {'_channel_skill_snapshot': [row.model_dump() for row in params.skill_snapshot]}
    with patch.object(llm, '_generate_response', return_value='Narration') as call:
        assert llm.generate_script(params.video_subject, app_config=cfg) == 'Narration'
        assert call.call_count == 1


def test_ui_approval_freezes_blueprint_without_starting_video():
    with patch.dict(config.ui, {}, clear=True), patch.object(task, 'start') as start:
        app = AppTest.from_string(UI).run()
        app.checkbox(key='channel_skills_enabled').check().run()
        app.multiselect(key='channel_skill_ids').select(story.SKILL_ID).run()
        app.session_state['bta_blueprint'] = supported().model_dump()
        app.run()
        app.checkbox(key='bta_evidence_reviewed').check().run()
        app.button(key='bta_review').click().run()
        assert not app.exception
        assert not app.button(key='bta_approve').disabled
        app.button(key='bta_approve').click().run()
        assert not app.exception
        # UI params topic differs (Operation Gold vs full title); explicit matching is required.
        assert app.session_state['bta_approved']['approved_for_script']
        assert story.MARKER not in app.session_state['captured']['skill_snapshot'][0]['content']
        app.session_state['video_subject'] = supported().input_topic
        app.run()
        assert not app.exception
        assert story.MARKER in app.session_state['captured']['skill_snapshot'][0]['content']
        start.assert_not_called()
