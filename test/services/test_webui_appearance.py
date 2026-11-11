"""Theme switching persists through the existing config without changing video settings."""
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest
from app.config import config

SCRIPT='''
import streamlit as st
from webui import appearance
appearance.apply()
appearance.render_control()
st.text_input('Título')
st.warning('Aviso de pesquisa')
'''


def test_theme_change_is_saved_and_restored_on_fresh_page(monkeypatch):
    values={'font_size':60,'voice_name':'saved-voice'}
    monkeypatch.setattr(config,'ui',values)
    monkeypatch.setattr(config,'snapshot_config_with_pending',lambda source:dict(source))
    update=Mock(side_effect=lambda section,key,value:section.update({key:value}))
    save=Mock(return_value=True)
    monkeypatch.setattr(config,'update_config_nonblocking',update)
    monkeypatch.setattr(config,'try_save_config',save)
    app=AppTest.from_string(SCRIPT).run()
    assert not app.exception
    app.selectbox(key='mpt_appearance_theme').select('dark').run()
    assert not app.exception
    assert values=={'font_size':60,'voice_name':'saved-voice','appearance_theme':'dark'}
    update.assert_called_once();save.assert_called_once()
    fresh=AppTest.from_string(SCRIPT).run()
    assert fresh.selectbox(key='mpt_appearance_theme').value=='dark'
    fresh.selectbox(key='mpt_appearance_theme').select('system').run()
    assert values['appearance_theme']=='system'


def test_unknown_saved_theme_recovers_to_light_without_writing_config(monkeypatch):
    monkeypatch.setattr(config,'ui',{'appearance_theme':'invalid'})
    monkeypatch.setattr(config,'snapshot_config_with_pending',lambda source:dict(source))
    write=Mock();monkeypatch.setattr(config,'update_config_nonblocking',write)
    app=AppTest.from_string(SCRIPT).run()
    assert not app.exception and app.selectbox(key='mpt_appearance_theme').value=='light'
    write.assert_not_called()
