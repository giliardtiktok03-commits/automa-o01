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
