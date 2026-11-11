from pathlib import Path
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from app.models.autopilot import ChannelProfile
from app.services.autopilot.repository import Repository
from app.services.autopilot import recovery, worker


def app_script(path):
    return f'''
from webui.autopilot import render
from app.services.autopilot.repository import Repository
render(repository=Repository({str(path)!r}), autostart=False)
'''


def test_channel_and_enabled_setting_survive_a_fresh_page(tmp_path):
    path = tmp_path / 'autopilot.sqlite3'
    app = AppTest.from_string(app_script(path)).run()
    assert not app.exception
    app.text_input[0].set_value('cooking')
    app.text_input[1].set_value('Receitas')
    app.text_input[3].set_value('Culinária')
    app.checkbox[1].check()
    next(b for b in app.button if b.label == 'Salvar canal').click().run()
    assert not app.exception
    assert Repository(path).channels()[0]['channel_id'] == 'cooking'
    assert app.selectbox(key='autopilot_channel_edit').value == 'cooking'
    app.checkbox(key='autopilot_worker_enabled').check().run()
    assert Repository(path).enabled()
    fresh = AppTest.from_string(app_script(path)).run()
    assert not fresh.exception
    assert fresh.checkbox(key='autopilot_worker_enabled').value is True
    assert 'cooking' in fresh.selectbox(key='autopilot_channel_edit').options or 'Receitas' in fresh.selectbox(key='autopilot_channel_edit').options


def test_discovery_panel_has_no_uuid_input_or_publish_button(tmp_path, monkeypatch):
    path = tmp_path / 'autopilot.sqlite3'
    repo = Repository(path)
    repo.save_channel(ChannelProfile(channel_id='history', name='History'))
    candidate = {'task_id': '2d6613a1-c254-484c-a078-4d43f05283fa', 'title': 'Original title', 'registered': 168, 'total': 280, 'editorial_digest': 'a'*64}
    monkeypatch.setattr(recovery, 'discover', lambda: [candidate])
    monkeypatch.setattr(recovery, 'inspect', lambda *a, **kw: candidate)
    app = AppTest.from_string(app_script(path)).run()
    app.button(key='autopilot_discover').click().run()
    assert not app.exception
    app.button(key='autopilot_enroll').click().run()
    assert not app.exception
    assert len(repo.jobs()) == 1
    app.button(key='autopilot_enroll').click().run()
    assert len(repo.jobs()) == 1
    assert not any('ID da tarefa' in x.label for x in app.text_input)
    assert not any('Publicar' in x.label for x in app.button)


def test_journal_failure_keeps_manual_generation_available(tmp_path, monkeypatch):
    import sqlite3
    from app.config import config
    from app.services import version_checker
    from webui import autopilot
    monkeypatch.setattr(autopilot, 'Repository', Mock(side_effect=sqlite3.DatabaseError('broken journal')))
    monkeypatch.setattr(config, 'try_save_config', lambda *a, **kw: True)
    monkeypatch.setattr(version_checker, 'get_available_update', lambda *a, **kw: None)
    main = Path(__file__).parents[2] / 'webui/Main.py'
    app = AppTest.from_file(str(main), default_timeout=60).run()
    assert not app.exception
    assert app.button(key='generate_video_button') is not None
    assert any('fluxo manual continua' in message.value for message in app.warning)


def test_channel_reuses_existing_skill_panel_selection(tmp_path):
    path=tmp_path/'autopilot.sqlite3'
    script=f'''
from webui.autopilot import render
from app.models.schema import VideoParams
from app.services.autopilot.repository import Repository
render(VideoParams(video_subject='Preview',skills_enabled=True,skill_ids=['primary','supplement']),repository=Repository({str(path)!r}),autostart=False)
'''
    app=AppTest.from_string(script).run()
    app.text_input[0].set_value('archives')
    app.text_input[1].set_value('Archives')
    next(c for c in app.checkbox if c.label=='Autorizar pesquisa e roteiro automáticos para este canal').check()
    next(b for b in app.button if b.label=='Salvar canal').click().run()
    assert not app.exception
    profile=Repository(path).channels()[0]
    assert profile['skill_ids']==['primary','supplement'] and profile['auto_editorial']
    # Existing channels keep their saved Skills until the user chooses to sync.
    assert not app.checkbox(key='autopilot_sync_skills_archives').value


def test_new_title_submission_and_preflight_error_are_visible(tmp_path,monkeypatch):
    from app.models.autopilot_editorial import EditorialSnapshot
    from app.services.autopilot import editorial
    from app.services.autopilot.recovery import RecoveryBlocked
    path=tmp_path/'journal.sqlite3';repo=Repository(path)
    profile=ChannelProfile(channel_id='history',name='History',auto_editorial=True)
    repo.save_channel(profile)
    prepare=Mock(return_value=EditorialSnapshot(channel=profile,script_provider='openai',script_model='configured-model'))
    monkeypatch.setattr(editorial,'prepare',prepare)
    app=AppTest.from_string(app_script(path)).run()
    app.text_input(key='autopilot_new_title').set_value('Original title')
    next(b for b in app.button if b.label=='Pesquisar e gerar roteiro').click().run()
    assert not app.exception and len(repo.editorial_jobs())==1
    assert prepare.call_args.args[0].channel_id=='history'
    next(b for b in app.button if b.label=='Pesquisar e gerar roteiro').click().run()
    assert len(repo.editorial_jobs())==1
    prepare.side_effect=RecoveryBlocked('Configure a chave da API OpenAI para pesquisar fontes')
    next(b for b in app.button if b.label=='Pesquisar e gerar roteiro').click().run()
    assert not app.exception and any('chave da API' in error.value for error in app.error)
