"""A server failure never reposts unless a specific scene is explicitly authorized."""
import json
from unittest.mock import Mock
import pytest
import requests
from streamlit.testing.v1 import AppTest
from app.models.schema import VideoParams
from app.services import deepinfra_image as api,deepinfra_recovery as recovery
from test.services.test_mixed_resume import saved_project,ID
from test.services.test_deepinfra_flux import encoded_image
from test.services.test_mixed_materials import setup as mixed_setup,SCRIPT


@pytest.fixture
def failed(saved_project,monkeypatch,tmp_path):
    folder,manifest,_=saved_project
    monkeypatch.delenv('DEEPINFRA_API_KEY',raising=False)
    monkeypatch.setattr(api,'_rate_file',lambda key:tmp_path/'rate.json')
    params=VideoParams(video_subject='Test',deepinfra_model=api.P_IMAGE_MODEL,video_aspect='16:9')
    settings={'deepinfra_api_key':'test-secret'}
    scene_dir=folder/'mixed/deepinfra-001'
    post=Mock(side_effect=api.DeepInfraHTTPError(500));monkeypatch.setattr(api,'_post',post)
    with pytest.raises(api.DeepInfraHTTPError):api.generate(params,'Scene prompt',scene_dir,settings=settings)
    manifest['scenes'][0].update(image_request_started=True,deepinfra_job='deepinfra-001')
    (folder/'mixed-scenes.json').write_text(json.dumps(manifest))
    state=json.loads((scene_dir/'deepinfra-image.json').read_text())
    return folder,scene_dir,params,settings,post,state


def test_explicit_retry_reuses_project_audio_and_only_one_new_post(failed):
    folder,scene,params,settings,post,state=failed
    original={name:(folder/name).read_bytes() for name in ('custom-audio.mp3','script.json','mixed-scenes.json')}
    assert recovery.failures(ID)==[{'scene_id':1,'http_status':500,'request_id':state['request_id']}]
    with pytest.raises(api.DeepInfraError,match='Sem novo envio'):api.generate(params,'Scene prompt',scene,settings=settings,existing_only=True)
    assert post.call_count==1
    recovery.authorize(ID,1,state['request_id'],24)
    assert post.call_count==1 and not recovery.failures(ID)
    with pytest.raises(ValueError,match='mudou|autorizada'):recovery.authorize(ID,1,state['request_id'],24)
    post.side_effect=None;post.return_value=json.dumps({'data':[{'b64_json':encoded_image()}]}).encode()
    mark=Mock()
    image,_=api.generate(params,'Scene prompt',scene,settings=settings,existing_only=True,before_submit=mark)
    assert image.is_file() and post.call_count==2 and mark.call_count==1
    api.generate(params,'Scene prompt',scene,settings=settings,existing_only=True,before_submit=mark)
    assert post.call_count==2 and mark.call_count==1
    final=json.loads((scene/'deepinfra-image.json').read_text())
    assert final['request_id']!=state['request_id'] and final['attempt_history'][0]['http_status']==500
    assert 'test-secret' not in json.dumps(final)
    assert all((folder/name).read_bytes()==data for name,data in original.items())


def test_retry_failure_requires_another_explicit_authorization(failed):
    _,scene,params,settings,post,state=failed
    recovery.authorize(ID,1,state['request_id'],24)
    with pytest.raises(api.DeepInfraHTTPError):api.generate(params,'Scene prompt',scene,settings=settings,existing_only=True)
    with pytest.raises(api.DeepInfraError):api.generate(params,'Scene prompt',scene,settings=settings,existing_only=True)
    assert post.call_count==2
    with pytest.raises(ValueError):recovery.authorize(ID,1,state['request_id'],24)


@pytest.mark.parametrize('status',[401,403,422,None])
def test_auth_refusal_and_ambiguous_timeout_are_not_offered_for_retry(failed,status):
    _,scene,params,settings,post,state=failed
    state.update(status='http_error' if status else 'submission_unconfirmed',http_status=status)
    (scene/'deepinfra-image.json').write_text(json.dumps(state))
    assert not recovery.failures(ID)
    with pytest.raises(ValueError):recovery.authorize(ID,1,state['request_id'],24)
    assert post.call_count==1


def test_retry_obeys_total_budget_and_changed_prompt(failed):
    _,scene,params,settings,post,state=failed
    with pytest.raises(ValueError,match='limite'):recovery.authorize(ID,1,state['request_id'],12)
    recovery.authorize(ID,1,state['request_id'],13)
    with pytest.raises(api.DeepInfraError,match='configurações'):api.generate(params,'Changed prompt',scene,settings=settings,existing_only=True)
    assert post.call_count==1


def test_interrupted_authorized_retry_does_not_repost_after_timeout(failed):
    _,scene,params,settings,post,state=failed
    recovery.authorize(ID,1,state['request_id'],24)
    post.side_effect=requests.Timeout()
    with pytest.raises(api.DeepInfraError):api.generate(params,'Scene prompt',scene,settings=settings,existing_only=True)
    with pytest.raises(api.DeepInfraError):api.generate(params,'Scene prompt',scene,settings=settings,existing_only=True)
    assert post.call_count==2 and not recovery.failures(ID)


def test_ui_requires_scene_specific_consent_and_does_not_submit(failed,monkeypatch):
    _,scene,params,settings,post,state=failed
    from app.services import webui_task
    monkeypatch.setattr(webui_task,'is_generation_active',lambda _:False)
    app=AppTest.from_string(f'''
from webui.deepinfra_recovery import render
render({ID!r},24)
''').run()
    assert not app.exception and app.button[0].disabled
    app.checkbox[0].check().run()
    app.button[0].click().run()
    assert not app.exception and app.success
    assert json.loads((scene/'deepinfra-image.json').read_text())['status']=='retry_authorized'
    assert post.call_count==1


def test_mixed_pipeline_resumes_failed_scene_and_counts_new_request(mixed_setup,monkeypatch,tmp_path):
    from app.services import mixed_materials as mixed
    folder,subtitles,params,*_=mixed_setup
    params.mixed_use_deepinfra=True
    params.mixed_deepinfra_unlimited=False
    params.mixed_max_images=1
    mixed.config.app.update(deepinfra_api_key='test-key',deepinfra_image_model=api.P_IMAGE_MODEL)
    monkeypatch.setattr(api,'_rate_file',lambda key:tmp_path/'rate.json')
    post=Mock(side_effect=api.DeepInfraHTTPError(500));monkeypatch.setattr(api,'_post',post)
    with pytest.raises(mixed.MixedError,match='HTTP 500'):mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    before=(folder/'mixed/scene-001.mp4').read_bytes()
    manifest=json.loads((folder/'mixed-scenes.json').read_text())
    assert manifest['image_requests']==1
    ledger=folder/'mixed/deepinfra-002/deepinfra-image.json'
    state=json.loads(ledger.read_text())
    state.update(status='retry_authorized',retry_for=state['request_id'])
    ledger.write_text(json.dumps(state))
    params.mixed_resume=True
    with pytest.raises(mixed.MixedError,match='limite total'):mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert json.loads(ledger.read_text())['status']=='retry_authorized' and post.call_count==1
    params.mixed_max_images=2
    post.side_effect=None;post.return_value=json.dumps({'data':[{'b64_json':encoded_image()}]}).encode()
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert post.call_count==2
    assert (folder/'mixed/scene-001.mp4').read_bytes()==before
    assert json.loads((folder/'mixed-scenes.json').read_text())['image_requests']==2
