import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest
from app.models.schema import VideoParams
from app.services import grok_image as grok


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(grok.config,'app',{'grok_image_api_key':'private-test-key'})
    output=io.BytesIO()
    Image.new('RGB',(160,90),'blue').save(output,format='PNG')
    client=Mock()
    client.__enter__=Mock(return_value=client)
    client.__exit__=Mock(return_value=None)
    client.image.sample.return_value=SimpleNamespace(respect_moderation=True,base64=base64.b64encode(output.getvalue()).decode(),cost_usd=0.02)
    create=Mock(return_value=client)
    monkeypatch.setattr(grok,'_client',create)
    return VideoParams(video_subject='History',video_aspect='16:9'),client,create


def test_single_image_cached_and_resumed_without_another_paid_call(setup,tmp_path):
    params,client,create=setup
    before=Mock()
    image,metadata=grok.generate(params,'Historically accurate scene',tmp_path,before_submit=before)
    again,_=grok.generate(params,'Historically accurate scene',tmp_path,existing_only=True)
    assert image==again and metadata['cost_usd']==0.02
    client.image.sample.assert_called_once_with(model='grok-imagine-image',prompt='Historically accurate scene',aspect_ratio='16:9',image_format='base64')
    before.assert_called_once()
    assert Image.open(image).size==(160,90)
    assert 'private-test-key' not in (tmp_path/'grok-image.json').read_text()
    assert not (tmp_path/'response.b64').exists()


def test_timeout_never_resubmits_or_switches_provider(setup,tmp_path):
    params,client,_=setup
    client.image.sample.side_effect=RuntimeError('transport failure private-test-key')
    with pytest.raises(grok.GrokError) as error:
        grok.generate(params,'Historic scene',tmp_path)
    assert 'private-test-key' not in str(error.value)
    with pytest.raises(grok.GrokError,match='não confirmado'):
        grok.generate(params,'Historic scene',tmp_path,existing_only=True)
    client.image.sample.assert_called_once()


def test_missing_sdk_fails_before_recording_a_paid_attempt(setup,tmp_path):
    params,_,_=setup
    with patch.object(grok,'_client',side_effect=grok.GrokError('Install SDK')):
        with pytest.raises(grok.GrokError):
            grok.generate(params,'Historic scene',tmp_path)
    assert not (tmp_path/'grok-image.json').exists()


def test_existing_only_cannot_submit_when_record_is_missing(setup,tmp_path):
    params,client,_=setup
    with pytest.raises(grok.GrokError,match='ausente'):
        grok.generate(params,'Historic scene',tmp_path,existing_only=True)
    client.image.sample.assert_not_called()


def test_changed_prompt_cannot_reuse_or_replace_paid_task(setup,tmp_path):
    params,client,_=setup
    grok.generate(params,'Historic scene',tmp_path)
    with pytest.raises(grok.GrokError,match='diferem'):
        grok.generate(params,'Another scene',tmp_path)
    client.image.sample.assert_called_once()


def test_moderation_refusal_is_not_reworded_or_retried(setup,tmp_path):
    params,client,_=setup
    client.image.sample.return_value=SimpleNamespace(respect_moderation=False)
    with pytest.raises(grok.GrokError,match='segurança'):
        grok.generate(params,'Historic scene',tmp_path)
    assert json.loads((tmp_path/'grok-image.json').read_text())['status']=='refused'
    client.image.sample.assert_called_once()


def test_official_sdk_retries_disabled_and_no_alternative_host():
    sdk=SimpleNamespace(Client=Mock())
    with patch.dict('sys.modules',{'xai_sdk':sdk}):
        grok._client('private-test-key',600)
    kwargs=sdk.Client.call_args.kwargs
    assert ('grpc.enable_retries',0) in kwargs['channel_options']
    assert kwargs['api_key']=='private-test-key' and kwargs['timeout']==600
    assert 'api_host' not in kwargs


def test_grok_settings_mask_key_and_only_generate_on_explicit_click():
    script='''
import streamlit as st
from webui.grok_settings import render
if 'settings' not in st.session_state: st.session_state.settings={}
def save(section,key,value): st.session_state.settings[key]=value
render(dict(st.session_state.settings),save)
'''
    with patch.object(grok,'generate') as paid:
        app=AppTest.from_string(script).run()
        assert not app.exception
        app.text_input(key='grok_image_api_key_input').set_value('private-test-key').run()
        assert not app.exception
        assert app.text_input(key='grok_image_api_key_input').proto.type==1
        assert app.session_state.settings['grok_image_model']=='grok-imagine-image'
        paid.assert_not_called()


def test_default_source_is_grok_with_ai33_and_runware_disabled():
    params=VideoParams(video_subject='History')
    assert params.mixed_image_provider=='grok' and params.mixed_use_grok
    assert not params.mixed_use_ai33 and not params.mixed_use_runware


def test_previous_runware_chapter_can_migrate_only_image_settings(tmp_path):
    from app.services import long_form, task_artifacts
    old=VideoParams(video_subject='History',video_source='mixed',mixed_image_provider='runware',
                    mixed_use_runware=True,mixed_use_grok=False,runware_model='runware:100@1',runware_size=1024,runware_steps=4)
    saved=old.model_dump(mode='json')
    saved.pop('grok_model')
    saved.pop('mixed_use_grok')
    references=['audio-digest']
    fingerprint=long_form._fingerprint(old,references)
    manifest={'version':1,'fingerprint':fingerprint,'chapters':[]}
    task_artifacts._write_json_atomic(tmp_path/'script.json',{'params':saved})
    task_artifacts._write_json_atomic(tmp_path/'chapters.json',manifest)
    new=old.model_copy(update={'mixed_image_provider':'grok','mixed_use_runware':False,'mixed_use_grok':True,'grok_model':grok.DEFAULT_MODEL})
    assert long_form._migrate_image_provider(new,references,tmp_path,manifest)
    assert manifest['continuation_image_provider']=='grok_image'
    assert not long_form._migrate_image_provider(new.model_copy(update={'voice_name':'different'}),references,tmp_path,{'fingerprint':fingerprint})


def test_grok_model_is_part_of_chapter_fingerprint():
    from app.services import long_form
    params=VideoParams(video_subject='History',video_source='mixed',grok_model=grok.DEFAULT_MODEL)
    assert long_form._fingerprint(params,[])!=long_form._fingerprint(params.model_copy(update={'grok_model':'another-model'}),[])


def test_image_key_is_separate_from_existing_grok_text_configuration(monkeypatch):
    monkeypatch.delenv('XAI_API_KEY',raising=False)
    params=VideoParams(video_subject='History')
    with pytest.raises(grok.GrokError,match='chave'):
        grok.freeze(params,{'grok_api_key':'text-only-key'})
    grok.freeze(params,{'grok_image_api_key':'image-only-key'})
    assert params.grok_model==grok.DEFAULT_MODEL


@pytest.mark.parametrize('mime', ['image/png', 'image/jpeg', 'image/webp'])
def test_sdk_data_uri_is_accepted_without_another_paid_request(setup,tmp_path,mime):
    params,client,_=setup
    encoded=client.image.sample.return_value.base64
    client.image.sample.return_value.base64=f'data:{mime};base64,{encoded}'
    image,_=grok.generate(params,'Historic scene',tmp_path)
    assert Image.open(image).size==(160,90)
    client.image.sample.assert_called_once()


def test_resume_existing_prefixed_response_recovers_without_sdk_or_paid_call(setup,tmp_path):
    params,client,_=setup
    encoded=client.image.sample.return_value.base64
    image,_=grok.generate(params,'Historic scene',tmp_path)
    image.unlink()
    state=json.loads((tmp_path/'grok-image.json').read_text())
    state['status']='received'
    state.pop('sha256',None)
    (tmp_path/'grok-image.json').write_text(json.dumps(state))
    (tmp_path/'response.b64').write_text('data:image/png;base64,\n'+encoded+'\n')
    client.image.sample.reset_mock()
    with patch.object(grok,'_client',side_effect=AssertionError('No SDK or paid request needed')):
        recovered,_=grok.generate(params,'Historic scene',tmp_path,existing_only=True)
    assert Image.open(recovered).size==(160,90)
    client.image.sample.assert_not_called()


@pytest.mark.parametrize('value',['data:text/html;base64,PHNjcmlwdD4=','data:image/png,not-base64','https://example.test/image.png','@@@not-base64'])
def test_invalid_saved_response_still_blocks_resubmission(setup,tmp_path,value):
    params,client,_=setup
    client.image.sample.return_value.base64=value
    with pytest.raises(grok.GrokError,match='não é uma imagem válida'):
        grok.generate(params,'Historic scene',tmp_path)
    with pytest.raises(grok.GrokError,match='não é uma imagem válida'):
        grok.generate(params,'Historic scene',tmp_path,existing_only=True)
    client.image.sample.assert_called_once()
