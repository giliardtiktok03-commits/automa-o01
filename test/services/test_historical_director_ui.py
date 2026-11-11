"""UI acceptance without external calls or billable generation."""
import json
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
from app.services.autopilot import editorial
from test.services.test_historical_director_queue import setup, analyzed


def app_script(repo,enabled=True):
    return f'''
from webui.historical_director import render
from app.services.autopilot.repository import Repository
from app.models.schema import VideoParams
render(VideoParams(video_subject='Preview',skills_enabled={enabled!r},skill_ids=['historical-documentary-director']),Repository({str(repo.path)!r}),autostart=False)
'''


def test_off_preserves_normal_flow_and_makes_no_analysis_call(setup,monkeypatch):
    repo,_=setup;paid=Mock();monkeypatch.setattr(editorial,'prepare',paid)
    app=AppTest.from_string(app_script(repo,False)).run()
    assert not app.exception
    assert not any(b.label=='Pesquisar referência e analisar ângulos' for b in app.button)
    assert not repo.director_batches();paid.assert_not_called()


def test_title_reference_and_channel_defaults_persist(setup,monkeypatch):
    repo,snapshot=setup;prepare=Mock(return_value=snapshot);monkeypatch.setattr(editorial,'prepare',prepare)
    app=AppTest.from_string(app_script(repo)).run()
    assert not app.exception
    app.text_input(key='director_reference_title_history').set_value('Original history title')
    app.text_area(key='director_reference_text_history').set_value('Reference opening and narrative structure, never factual proof.')
    app.text_area(key='director_central_history').set_value('Documented decisions and consequences')
    app.button(key='director_save_profile_history').click().run()
    assert not app.exception
    assert repo.director_profile('history')['central_angle']=='Documented decisions and consequences'
    app.button(key='director_submit_history').click().run()
    assert not app.exception and len(repo.director_batches())==1
    value=json.loads(repo.director_batches()[0]['request'])
    assert value['reference_script'].startswith('Reference opening')
    assert value['publish_mode']=='off'
    app.button(key='director_submit_history').click().run()
    assert len(repo.director_batches())==1
    assert prepare.call_count==2


def test_angle_off_hides_selection_and_automatic_requires_explicit_multiple(setup):
    repo,_=setup;app=AppTest.from_string(app_script(repo)).run()
    app.radio(key='director_mode_history').set_value('automatic').run()
    assert not app.exception
    assert not any(n.key=='director_top_n_history' for n in app.number_input)
    app.checkbox(key='director_multiple_history').check().run()
    assert app.number_input(key='director_top_n_history').value==1
    app.checkbox(key='director_angle_enabled_history').uncheck().run()
    assert not app.exception and not any(r.key=='director_mode_history' for r in app.radio)


def test_manual_select_three_reorder_and_enqueue(setup):
    repo,_=setup;batch,_=analyzed(setup)
    app=AppTest.from_string(app_script(repo)).run()
    assert not app.exception
    for i in [1,3,5]:app.checkbox(key=f'director_pick_{batch}_angle_0{i}').check()
    app.run()
    app.multiselect(key='director_selection_order_'+batch).set_value(['angle_05','angle_01','angle_03'])
    app.button(key='director_enqueue_'+batch).click().run()
    assert not app.exception
    assert [i['angle_id'] for i in repo.director_items(batch) if i['role']=='production']==['angle_05','angle_01','angle_03']
    fresh=AppTest.from_string(app_script(repo)).run()
    assert not fresh.exception
    assert len(repo.director_items(batch))==4


def test_select_all_and_clear(setup):
    repo,_=setup;batch,_=analyzed(setup)
    app=AppTest.from_string(app_script(repo)).run()
    app.button(key='director_all_'+batch).click().run()
    assert not app.exception
    assert all(app.checkbox(key=f'director_pick_{batch}_angle_0{i}').value for i in range(1,6))
    app.button(key='director_clear_'+batch).click().run()
    assert not any(app.checkbox(key=f'director_pick_{batch}_angle_0{i}').value for i in range(1,6))
