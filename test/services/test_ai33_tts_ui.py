"""Exercise actual Streamlit widgets without billable requests or Google OAuth."""
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest
from app.config import config
from app.services.ai33.tts import SpeechClient
from pathlib import Path


def test_catalog_requires_click_and_selected_voice_is_reused(monkeypatch):
    monkeypatch.setattr(config, 'app', {'ai33_api_key': 'test-key'})
    catalog=Mock(return_value={'voices': [
        {'voice_id':'elevenlabs_first','name':'First','language':'en','gender':'male'},
        {'voice_id':'minimax_second','name':'Second','language':'en','gender':'female'}], 'has_more':False})
    monkeypatch.setattr(SpeechClient,'voices',catalog)
    app=AppTest.from_string('''
import streamlit as st
from webui.ai33_tts import render
def save(group,key,value):
    st.session_state['saved_'+key]=value
value,_=render(save)
st.session_state['chosen']=value
''').run()
    assert not app.exception
    catalog.assert_not_called()
    app.button(key='ai33_voice_load').click().run()
    catalog.assert_called_once_with('English',1)
    assert app.session_state['chosen']=='ai33:elevenlabs_first'
    app.selectbox(key='ai33_voice_voice_1').set_value('minimax_second').run()
    assert not app.exception
    assert app.session_state['chosen']=='ai33:minimax_second'
    assert app.session_state['saved_ai33_tts_voice_id']=='minimax_second'
    assert catalog.call_count==1


def test_skill_narration_retains_fixed_voice_without_google(monkeypatch):
    monkeypatch.setattr(config,'app',{})
    monkeypatch.setattr(config,'try_save_config',lambda:None)
    catalog=Mock(side_effect=AssertionError('No automatic API call'))
    monkeypatch.setattr(SpeechClient,'voices',catalog)
    from app.services.youtube_publish.store import Store
    monkeypatch.setattr(Store,'connection',Mock(side_effect=AssertionError('No Google dependency')))
    app=AppTest.from_string('''
import streamlit as st
from app.models.historical_director import VideoProduction,PublicationOptions
from webui.historical_director import _production_options,_publication_options
defaults=VideoProduction(mode='narration',voice_name='ai33:elevenlabs_fixed',voice_rate=1.1)
value=_production_options(defaults,'demo')
st.session_state['options']=value
st.session_state['posting']=_publication_options(PublicationOptions(mode='prepare'),value,'demo')
''').run()
    assert not app.exception
    assert app.session_state['options']['voice_name']=='ai33:elevenlabs_fixed'
    assert app.session_state['options']['voice_rate']==1.1
    assert app.session_state['posting']=={'mode':'off'}
    catalog.assert_not_called()


def test_first_ai33_selection_keeps_form_editable_without_a_voice(monkeypatch):
    monkeypatch.setattr(config,'app',{})
    monkeypatch.setattr(config,'try_save_config',lambda:None)
    app=AppTest.from_string('''
import streamlit as st
from app.models.historical_director import VideoProduction
from webui.historical_director import _production_options
value=_production_options(VideoProduction(mode='narration'),'fresh')
st.session_state['options']=value
''').run()
    app.selectbox(key='director_voice_engine_fresh').set_value('ai33pro').run()
    assert not app.exception
    assert app.session_state['options']['voice_name']==''
    assert app.button(key='director_ai33_fresh_load').disabled


def test_main_audio_panel_uses_ai33_and_bounds_speed(monkeypatch):
    from app.services import voice
    monkeypatch.setattr(config,'ui',dict(config.ui,voice_mode='tts',tts_server='ai33pro',voice_name='ai33:elevenlabs_fixed'))
    monkeypatch.setattr(config,'app',dict(config.app,ai33_api_key='',ai33_tts_voice_id='elevenlabs_fixed'))
    monkeypatch.setattr(config,'try_save_config',lambda:None)
    monkeypatch.setattr(voice,'get_all_azure_voices',lambda **kwargs:[])
    catalog=Mock(side_effect=AssertionError('No request on render'))
    monkeypatch.setattr(SpeechClient,'voices',catalog)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'webui/Main.py'),default_timeout=30).run()
    assert not app.exception
    provider=next(x for x in app.selectbox if str(x.key).startswith('tts_server_select'))
    assert provider.value=='ai33pro'
    speed=next(x for x in app.selectbox if str(x.key).startswith('voice_rate_select'))
    assert all(float(option.rstrip('×'))<=1.5 for option in speed.options)
    catalog.assert_not_called()
