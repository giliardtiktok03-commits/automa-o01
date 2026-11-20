"""Visual prompts omit narration; recognized refusals are durable, not retried."""
import json
from unittest.mock import Mock,patch
import pytest
from app.models.schema import VideoParams
from app.services import deepinfra_image as api,deepinfra_recovery as recovery,mixed_materials as mixed
from test.services.test_mixed_resume import saved_project,ID
from test.services.test_mixed_materials import setup as mixed_setup,SCRIPT
from test.services.test_deepinfra_flux import response,session_for,encoded_image


@pytest.mark.parametrize('status',[422,500])
def test_recognized_upstream_moderation_is_refusal_and_never_reposted(tmp_path,monkeypatch,status):
    monkeypatch.setattr(api,'_rate_file',lambda key:tmp_path/'rate.json')
    client=session_for(response(status,data={'error':'Prediction failed: Content moderation: Blocked by content policy (violence).'}))
    params=VideoParams(video_subject='Test',deepinfra_model=api.P_IMAGE_MODEL)
    with patch.object(api.requests,'Session',return_value=client):
        for _ in range(2):
            with pytest.raises(api.DeepInfraRefusal):api.generate(params,'Naval office',tmp_path/'image',settings={'deepinfra_api_key':'test-key'})
    assert client.post.call_count==1
    assert 'disable_safety_checker' not in client.post.call_args.kwargs['json']
    ledger=(tmp_path/'image/deepinfra-image.json').read_text()
    assert json.loads(ledger)['status']=='refused' and 'Prediction failed' not in ledger


def test_existing_scene_migrates_prompt_only_with_explicit_recovery(saved_project,monkeypatch,tmp_path):
    folder,manifest,_=saved_project
    monkeypatch.setattr(api,'_rate_file',lambda key:tmp_path/'rate.json')
    scene=manifest['scenes'][0]
    scene.update(text='Shooting began. A crewman was killed.',image_prompt='Sailors sorting papers beside analog radios.',
                 context='historical',period='January 1968',location='USS Pueblo',deepinfra_job='deepinfra-001',image_request_started=True,
                 image_settings={'deepinfra_model':api.P_IMAGE_MODEL,'deepinfra_steps':1})
    (folder/'mixed-scenes.json').write_text(json.dumps(manifest))
    old_files={name:(folder/name).read_bytes() for name in ('custom-audio.mp3','script.json','mixed-scenes.json')}
    params=VideoParams(video_subject='Test',deepinfra_model=api.P_IMAGE_MODEL,deepinfra_steps=1)
    directory=folder/'mixed/deepinfra-001'
    post=Mock(side_effect=api.DeepInfraHTTPError(500));monkeypatch.setattr(api,'_post',post)
    with pytest.raises(api.DeepInfraHTTPError):api.generate(params,mixed.image_prompt(scene),directory,settings={'deepinfra_api_key':'key'})
    old_state=json.loads((directory/'deepinfra-image.json').read_text())
    assert 'Shooting began' in mixed.deepinfra_scene_prompt(scene,directory)[0]
    recovery.authorize(ID,1,old_state['request_id'],24,visual_only=True)
    prompt,mode=mixed.deepinfra_scene_prompt(scene,directory)
    assert mode=='visual-v1' and 'Shooting began' not in prompt and scene['image_prompt'] in prompt
    post.side_effect=None;post.return_value=json.dumps({'data':[{'b64_json':encoded_image()}]}).encode()
    api.generate(params,prompt,directory,settings={'deepinfra_api_key':'key'},existing_only=True,prompt_mode=mode)
    state=json.loads((directory/'deepinfra-image.json').read_text())
    assert state['prompt_mode']=='visual-v1' and state['attempt_history'][0]['fingerprint']==old_state['fingerprint']
    assert all((folder/name).read_bytes()==data for name,data in old_files.items())
    assert post.call_count==2


def test_new_deepinfra_scene_uses_visual_only_and_refusal_continues_pipeline(mixed_setup,monkeypatch):
    folder,subtitles,params,*_=mixed_setup
    params.mixed_use_deepinfra=True
    mixed.config.app.update(deepinfra_api_key='test-key',deepinfra_image_model=api.P_IMAGE_MODEL)
    post=Mock(side_effect=api.DeepInfraRefusal('Content policy'));monkeypatch.setattr(api,'_post',post)
    def card(scene,params,directory):
        path=directory/'card.png';path.write_bytes(b'editorial-card');return path
    monkeypatch.setattr(mixed,'_context_card',card)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    manifest=json.loads((folder/'mixed-scenes.json').read_text())
    scene=manifest['scenes'][1]
    assert scene['image_provider']=='editorial_card' and scene['image_refused']
    assert scene['text'] not in post.call_args.args[0]['prompt']
    assert scene['image_prompt'] in post.call_args.args[0]['prompt']
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert post.call_count==1
