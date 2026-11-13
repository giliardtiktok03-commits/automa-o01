"""The Skill workspace owns its full workflow; existing jobs/settings stay intact."""
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest
from app.config import config
from app.services.autopilot.repository import Repository
from app.services.autopilot import editorial
from app.services.historical_director.library import SKILL_ID
from test.services.test_historical_director_queue import setup,analyzed


def script(repo):
    return f'''
import streamlit as st
from webui.channel_skills import render
from webui.autopilot import render as render_autopilot
from app.services.autopilot.repository import Repository
from app.models.schema import VideoParams
params=VideoParams(video_subject='Preview')
repo=Repository({str(repo.path)!r})
owned=render(st.container(key='skills_workspace'),params,lambda *args:None,
    lambda n,label,color:st.markdown(f'{{n:02}} · {{label}}'),repository=repo,autostart=False)
render_autopilot(params,repository=repo,autostart=False,worker_control=not owned)
'''


def activate(monkeypatch):
    monkeypatch.setattr(config,'ui',{'skills_enabled':True,'skill_ids':[SKILL_ID]})


def test_full_workflow_nested_in_skill_and_no_duplicate_worker(setup,monkeypatch):
    repo,_=setup;activate(monkeypatch)
    batch,_=analyzed(setup)
    app=AppTest.from_string(script(repo)).run()
    assert not app.exception
    workspace=app.main.children[0]
    assert any(w.key=='director_reference_title_history' for w in workspace.get('text_input'))
    assert any(w.key=='director_pick_'+batch+'_angle_01' for w in workspace.get('checkbox'))
    assert any(w.key=='director_pause_'+batch for w in workspace.get('button'))
    assert sum(w.key=='autopilot_worker_enabled' for w in app.checkbox)==1
    assert any(w.key=='autopilot_worker_enabled' for w in workspace.get('checkbox'))
    assert not any(getattr(w,'key','')=='autopilot_new_title' for w in app.text_input)
    assert not any(getattr(w,'key','')=='autopilot_channel_form___new__' for w in app.get('form'))
    app.selectbox(key='autopilot_channel_edit').select('history').run()
    assert not app.exception
    assert not any(w.key=='autopilot_sync_skills_history' for w in app.checkbox)
    assert any(b.label=='Salvar opções de recuperação' for b in app.button)


def test_new_channel_can_be_created_and_authorized_inside_skill(setup,monkeypatch,tmp_path):
    activate(monkeypatch)
    repo=Repository(tmp_path/'fresh.sqlite3')
    paid=Mock();monkeypatch.setattr(editorial,'prepare',paid)
    app=AppTest.from_string(script(repo)).run()
    assert not app.exception
    app.text_input(key='director_channel_id___new__').set_value('archives')
    app.text_input(key='director_channel_name___new__').set_value('Beyond the Archives')
    app.text_input(key='director_channel_language___new__').set_value('en-US')
    app.checkbox(key='director_channel_permission___new__').check()
    next(b for b in app.button if b.label=='Salvar canal desta Skill').click().run()
    assert not app.exception
    assert app.selectbox(key='director_channel').value=='archives'
    stored=repo.channels()[0]
    assert stored['skill_ids']==[SKILL_ID] and stored['auto_editorial'] and stored['language']=='en-US'
    assert not app.button(key='director_submit_archives').disabled
    paid.assert_not_called()
    assert not repo.editorial_jobs()


def test_editing_skill_profile_preserves_recovery_and_job_snapshot(setup,monkeypatch):
    repo,snapshot=setup;activate(monkeypatch)
    batch,_=analyzed(setup)
    before=repo.get_editorial(repo.director_items(batch)[0]['task_id'])['snapshot']
    repo.save_channel(snapshot.channel.model_copy(update={'deepinfra_unlimited':True,'auto_resume':True,'image_limit':42}),expected_version=1)
    app=AppTest.from_string(script(repo)).run()
    app.text_input(key='director_channel_language_history').set_value('pt-BR')
    app.number_input(key='director_channel_minutes_history').set_value(7)
    next(b for b in app.button if b.label=='Salvar canal desta Skill').click().run()
    assert not app.exception
    profile=repo.channels()[0]
    assert profile['language']=='pt-BR' and profile['target_minutes']==7
    assert profile['deepinfra_unlimited'] and profile['auto_resume'] and profile['image_limit']==42
    assert repo.get_editorial(repo.director_items(batch)[0]['task_id'])['snapshot']==before


def test_research_starts_shared_execution_without_leaving_skill(setup,monkeypatch):
    repo,snapshot=setup;activate(monkeypatch);repo.set_enabled(False)
    prepare=Mock(return_value=snapshot);monkeypatch.setattr(editorial,'prepare',prepare)
    app=AppTest.from_string(script(repo)).run()
    app.text_input(key='director_reference_title_history').set_value('An independent historical question')
    app.button(key='director_submit_history').click().run()
    assert not app.exception
    assert repo.enabled() and app.checkbox(key='autopilot_worker_enabled').value
    assert len(repo.director_batches())==1
    prepare.assert_called_once()


def test_permission_cannot_be_bypassed_by_research_button(setup,monkeypatch):
    repo,snapshot=setup;activate(monkeypatch)
    repo.save_channel(snapshot.channel.model_copy(update={'auto_editorial':False}),expected_version=1)
    paid=Mock();monkeypatch.setattr(editorial,'prepare',paid)
    app=AppTest.from_string(script(repo)).run()
    assert not app.exception and app.button(key='director_submit_history').disabled
    assert not repo.editorial_jobs();paid.assert_not_called()


def test_existing_queue_remains_in_skill_when_skill_is_disabled(setup,monkeypatch):
    repo,_=setup;batch,_=analyzed(setup)
    monkeypatch.setattr(config,'ui',{'skills_enabled':False,'skill_ids':[SKILL_ID]})
    app=AppTest.from_string(script(repo)).run()
    assert not app.exception
    workspace=app.main.children[0]
    assert not any(w.key=='director_reference_title_history' for w in app.text_input)
    assert any(w.key=='director_pause_'+batch for w in workspace.get('button'))
    assert sum(w.key=='autopilot_worker_enabled' for w in app.checkbox)==1


def test_older_editorial_skill_result_moves_into_skill_even_when_disabled(setup,monkeypatch):
    from app.services.autopilot import worker
    repo,snapshot=setup
    task,_=repo.submit_editorial('Previous editorial test',snapshot)
    result={'title':'Previous editorial test','word_count':12,'script':'A saved original script from the prior editorial workflow.',
            'research':{'sources':[]},'metadata':{'description':'Original description','tags':['history']}}
    assert worker.run_once(repo,lambda job:result)
    monkeypatch.setattr(config,'ui',{'skills_enabled':False,'skill_ids':[SKILL_ID]})
    app=AppTest.from_string(script(repo)).run()
    assert not app.exception
    workspace=app.main.children[0]
    assert any(w.key=='autopilot_script_'+task for w in workspace.get('text_area'))
    assert sum(w.key=='autopilot_script_'+task for w in app.text_area)==1


def test_recovery_options_cannot_overwrite_skill_configuration(setup,monkeypatch):
    repo,_=setup;activate(monkeypatch)
    before={k:v for k,v in repo.channels()[0].items() if k!='version'}
    app=AppTest.from_string(script(repo)).run()
    app.selectbox(key='autopilot_channel_edit').select('history').run()
    next(w for w in app.checkbox if w.label=='DeepInfra sem limite de quantidade na recuperação').check()
    next(w for w in app.checkbox if w.label=='Autorizar recuperação automática dos projetos vinculados a este canal').check()
    next(w for w in app.button if w.label=='Salvar opções de recuperação').click().run()
    assert not app.exception
    after={k:v for k,v in repo.channels()[0].items() if k!='version'}
    assert after=={**before,'deepinfra_unlimited':True,'auto_resume':True}


def test_video_options_are_inside_skill_saved_per_channel_and_do_not_start_calls(setup,monkeypatch):
    repo,_=setup;activate(monkeypatch)
    paid=Mock();monkeypatch.setattr(editorial,'prepare',paid)
    app=AppTest.from_string(script(repo)).run()
    app.selectbox(key='director_output_history').select('video').run()
    assert not app.exception
    workspace=app.main.children[0]
    assert any(w.key=='director_image_model_history' for w in workspace.get('selectbox'))
    app.checkbox(key='director_image_unlimited_history').check()
    app.text_input(key='director_voice_history').set_value('en-US-GuyNeural-Male')
    app.button(key='director_save_profile_history').click().run()
    assert not app.exception
    saved=repo.director_profile('history')['production']
    assert saved['mode']=='video' and saved['deepinfra_model']=='PrunaAI/p-image'
    assert saved['deepinfra_unlimited'] and saved['voice_name']=='en-US-GuyNeural-Male'
    paid.assert_not_called()
    assert not repo.editorial_jobs()
