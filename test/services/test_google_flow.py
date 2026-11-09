import io
import json
from pathlib import Path
from unittest.mock import Mock,patch
from uuid import uuid4
from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app.models.schema import VideoParams
from app.services import google_flow as flow,flow_browser


def png(color='blue'):
    out=io.BytesIO()
    Image.new('RGB',(320,180),color).save(out,format='PNG')
    return out.getvalue()


@pytest.fixture
def exported(tmp_path,monkeypatch):
    monkeypatch.setattr(flow.utils,'task_dir',lambda task_id='':str(tmp_path/task_id))
    task_id=str(uuid4())
    directory=tmp_path/task_id
    directory.mkdir()
    scenes=[dict(id=i,text=f'Scene {i}',image_prompt=f'Visual {i}',context='current',period='today',location='test') for i in (1,2)]
    folder=flow.export(directory,{'scenes':scenes},'16:9',lambda scene:scene['image_prompt'])
    return task_id,folder


def test_export_import_out_of_order_and_idempotent_receive(exported):
    task_id,folder=exported
    flow.import_image(task_id,2,png('green'))
    flow.import_image(task_id,1,png('blue'))
    first,metadata=flow.receive(folder,1)
    assert metadata['scene_id']==1 and metadata['access_mode']=='manual_import'
    assert flow.receive(folder,2)[1]['scene_id']==2
    assert flow.import_image(task_id,1,png('blue'))==first
    with pytest.raises(flow.FlowError,match='preservado'):
        flow.import_image(task_id,1,png('red'))


def test_missing_image_waits_without_api_call(exported):
    _,folder=exported
    with patch('requests.sessions.Session.request') as network,pytest.raises(flow.FlowWaiting):
        flow.receive(folder,1)
    network.assert_not_called()


@pytest.mark.parametrize('content',[b'<html>not an image</html>',b'',b'fake png'])
def test_invalid_upload_is_rejected(exported,content):
    task_id,_=exported
    with pytest.raises(flow.FlowError):flow.import_image(task_id,1,content)


def test_invalid_project_path_and_unknown_scene_are_rejected(exported):
    task_id,_=exported
    with pytest.raises(flow.FlowError):flow.project('../../outside')
    with pytest.raises(flow.FlowError):flow.import_image(task_id,999,png())


def test_corrupt_saved_image_does_not_trigger_generation(exported):
    task_id,folder=exported
    image=flow.import_image(task_id,1,png())
    image.write_bytes(b'changed')
    with pytest.raises(flow.FlowError,match='alterado'):
        flow.receive(folder,1)


def test_browser_mode_can_reuse_manual_recovery_without_resubmitting(exported):
    task_id,folder=exported
    flow.import_image(task_id,1,png())
    params=VideoParams(video_subject='Test',google_flow_mode='automatic')
    with patch.object(flow_browser,'generate') as generate:
        image,_=flow.generate(params,'Visual 1',folder,1,folder/'job')
    assert image.is_file()
    generate.assert_not_called()


def test_automatic_mode_sends_one_image_and_records_source(exported):
    _,folder=exported
    target=folder/'download.png'
    target.write_bytes(png())
    params=VideoParams(video_subject='Test',google_flow_mode='automatic',google_flow_profile='principal',
        google_flow_project_url='https://flow.google.com/project/'+str(uuid4()),google_flow_model='Nano Banana 2.1',google_flow_timeout=900,google_flow_require_zero=True)
    with patch.object(flow_browser,'generate',return_value=target) as generate:
        image,meta=flow.generate(params,'Visual 1',folder,1,folder/'job')
        flow.generate(params,'Visual 1',folder,1,folder/'job')
    generate.assert_called_once()
    assert image.is_file() and meta['access_mode']=='automatic' and meta['illustration']


def test_settings_never_connect_or_generate_on_render():
    script='''
import streamlit as st
from webui.google_flow_settings import render
if 'settings' not in st.session_state:st.session_state.settings={}
def save(section,key,value):st.session_state.settings[key]=value
render(dict(st.session_state.settings),save)
'''
    with patch.object(flow_browser,'connect') as connect,patch.object(flow_browser,'start_test') as paid:
        app=AppTest.from_string(script).run()
        assert not app.exception
        assert app.selectbox(key='google_flow_mode_input').value=='automatic'
        assert app.checkbox(key='google_flow_zero_input').value
        connect.assert_not_called()
        paid.assert_not_called()


def test_chapter_import_stays_inside_project_folder(tmp_path,monkeypatch):
    monkeypatch.setattr(flow.utils,'task_dir',lambda task_id='':str(tmp_path/task_id))
    task_id=str(uuid4())
    folder=tmp_path/task_id/'chapters'/'001'/'google-flow'
    folder.mkdir(parents=True)
    assert flow.project(task_id+'/chapters/001')==folder
    for suffix in ('/chapters/../outside','/chapters/000','/chapters/001/../../outside'):
        with pytest.raises(flow.FlowError):flow.project(task_id+suffix)


def test_global_flow_source_defaults_to_static_without_changing_grok_settings():
    from app.config import config
    from app.services import version_checker
    root=Path(__file__).resolve().parents[2]
    with patch.dict(config.app,{'video_source':'google_flow','llm_provider':'openai','google_flow_access_mode':'manual_import'},clear=True),patch.dict(config.ui,{'language':'pt','image_motion':'zoom'},clear=True),patch.object(config,'try_save_config',return_value=True),patch.object(version_checker,'get_available_update',return_value=None):
        app=AppTest.from_file(str(root/'webui/Main.py'),default_timeout=30).run()
        assert not app.exception
        choices=[widget for widget in app.selectbox if str(widget.key).startswith('flow_image_motion_select')]
        assert len(choices)==1 and choices[0].value=='static'
        assert config.ui['image_motion']=='zoom'
