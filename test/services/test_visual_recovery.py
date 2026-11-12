"""Technical vision failures never approve footage; only selected DeepInfra may continue."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.services import visual_validation as visual
from app.services import mixed_materials as mixed
from test.services.test_visual_validation import inspection
from test.services.test_mixed_materials import setup,SCRIPT


def reply(relevant=True):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
        'relevant':relevant,'confidence':0.95,'reason':'Direct visual match' if relevant else 'Unrelated footage'})))])


def test_transient_failure_retries_once_then_valid_verdict_is_cached(inspection):
    directory,scene,settings,_,create,_=inspection
    create.side_effect=[TimeoutError('never-store-this-key'),reply()]
    accepted,_=visual.inspect_clip('video.mp4',scene,directory,settings,'vision-test')
    assert accepted and create.call_count==2
    assert visual.inspect_clip('video.mp4',scene,directory,settings,'vision-test')[0]
    assert create.call_count==2
    errors=(directory/'visual-errors.json').read_text()
    assert 'timeout' in errors and 'never-store-this-key' not in errors


def test_invalid_verdict_stops_after_two_and_is_never_cached_as_approval(inspection):
    directory,scene,settings,_,create,_=inspection
    create.return_value.choices[0].message.content='not-json'
    with pytest.raises(visual.VisualAPIError) as captured:
        visual.inspect_clip('video.mp4',scene,directory,settings,'vision-test')
    assert create.call_count==2 and captured.value.code=='invalid_verdict'
    assert captured.value.attempts==2
    assert not (directory/'visual-checks.json').exists()
    assert len(next(iter(json.loads((directory/'visual-errors.json').read_text()).values())))==2


@pytest.mark.parametrize('status,expected,attempts',[(401,'authentication',1),(403,'authentication',1),(429,'rate_limit',1),(400,'invalid_request',1),(503,'service',2)])
def test_http_failures_are_categorized_without_secret_or_unbounded_retries(inspection,status,expected,attempts):
    directory,scene,settings,_,create,_=inspection
    error=RuntimeError('private headers never-store-this-key')
    error.status_code=status
    create.side_effect=error
    with pytest.raises(visual.VisualAPIError) as captured:
        visual.inspect_clip('video.mp4',scene,directory,settings,'vision-test')
    assert captured.value.code==expected and captured.value.status==status
    assert captured.value.attempts==attempts and create.call_count==attempts
    assert 'private headers' not in str(captured.value)+(directory/'visual-errors.json').read_text()


def test_fenced_valid_json_is_accepted_without_retry(inspection):
    directory,scene,settings,_,create,_=inspection
    create.return_value.choices[0].message.content='```json\n'+reply().choices[0].message.content+'\n```'
    assert visual.inspect_clip('video.mp4',scene,directory,settings,'vision-test')[0]
    create.assert_called_once()


def deepinfra_setup(setup,monkeypatch):
    folder,subtitles,params,_,_,_,_=setup
    params.mixed_select_sources=True
    params.mixed_use_deepinfra=True
    params.mixed_visual_validation=True
    params.mixed_deepinfra_unlimited=True
    mixed.config.app.update(deepinfra_api_key='unit-key',deepinfra_image_model='PrunaAI/p-image',openai_api_key='unit-vision')
    def generate(job_params,prompt,directory,*,before_submit=None,**kwargs):
        assert job_params.deepinfra_model=='PrunaAI/p-image'
        before_submit()
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        path=directory/'image.png';path.write_bytes(prompt.encode())
        return path,{'model':'PrunaAI/p-image'}
    provider=Mock(side_effect=generate)
    monkeypatch.setattr(mixed.deepinfra_image,'generate',provider)
    return folder,subtitles,params,provider


def test_approved_scene_preserved_failed_vision_uses_selected_pruna_and_resumes(setup,monkeypatch):
    folder,subtitles,params,provider=deepinfra_setup(setup,monkeypatch)
    def inspect(path,scene,*args,**kwargs):
        if scene['id']==1:return True,{'relevant':True,'confidence':.95,'reason':'Direct match'}
        raise visual.VisualAPIError('invalid_verdict',2)
    vision=Mock(side_effect=inspect);monkeypatch.setattr(mixed.visual_validation,'inspect_clip',vision)
    outputs=mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert len(outputs)==3 and provider.call_count==2
    manifest=json.loads((folder/'mixed-scenes.json').read_text())
    assert manifest['scenes'][0]['provenance']['provider']=='pexels'
    assert manifest['scenes'][1]['visual_validation_error']['approved'] is False
    assert manifest['scenes'][1]['image_provider']=='deepinfra_image'
    assert manifest['image_requests']==2
    before=vision.call_count
    params.mixed_resume=True
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert provider.call_count==2 and vision.call_count==before


def test_failure_does_not_bypass_deepinfra_image_budget(setup,monkeypatch):
    _,subtitles,params,provider=deepinfra_setup(setup,monkeypatch)
    params.mixed_deepinfra_unlimited=False;params.mixed_max_images=0
    monkeypatch.setattr(mixed.visual_validation,'inspect_clip',Mock(side_effect=visual.VisualAPIError('timeout',2)))
    with pytest.raises(mixed.MixedError,match='image limit'):
        mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    provider.assert_not_called()


def test_other_generators_are_not_silently_selected_on_visual_api_failure(setup,monkeypatch):
    _,subtitles,params,_,_,images,_=setup
    params.mixed_visual_validation=True
    mixed.config.app['openai_api_key']='unit-vision'
    monkeypatch.setattr(mixed.visual_validation,'inspect_clip',Mock(side_effect=visual.VisualAPIError('timeout',2)))
    with pytest.raises(mixed.MixedError) as captured:
        mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert captured.value.key=='mixed.vision_failed'
    images.assert_not_called()


def test_frame_decode_failure_is_not_treated_as_api_failure(setup,monkeypatch):
    _,subtitles,params,provider=deepinfra_setup(setup,monkeypatch)
    monkeypatch.setattr(mixed.visual_validation,'inspect_clip',Mock(side_effect=visual.VisualValidationError('Could not extract frames')))
    with pytest.raises(mixed.MixedError):mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    provider.assert_not_called()


def test_invalid_field_is_recorded_without_logging_response_text(inspection):
    directory,scene,settings,_,create,_=inspection
    create.return_value.choices[0].message.content=json.dumps({'relevant':True,'confidence':2,'reason':'never-store-this-key'})
    with pytest.raises(visual.VisualAPIError):
        visual.inspect_clip('video.mp4',scene,directory,settings,'vision-test')
    text=(directory/'visual-errors.json').read_text()
    entries=next(iter(json.loads(text).values()))
    assert entries[-1]['invalid_fields']==[{'field':'confidence','error':'less_than_equal'}]
    assert 'never-store-this-key' not in text
