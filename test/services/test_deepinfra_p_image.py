"""P-Image reuses the existing DeepInfra HTTP/base64/cache/PNG path."""
import base64
import json
import os
from unittest.mock import Mock,patch
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from app.models.schema import VideoParams
from app.services import deepinfra_image as api
from test.services.test_deepinfra_flux import encoded_image,response,session_for


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.delenv('DEEPINFRA_API_KEY',raising=False)
    monkeypatch.delenv('DEEPINFRA_IMAGE_MODEL',raising=False)
    monkeypatch.setattr(api,'_rate_file',lambda key:tmp_path/'rate.json')


def test_exact_p_image_model_openai_endpoint_one_image_and_png_16_9(tmp_path,caplog):
    client=session_for(response())
    settings={'deepinfra_api_key':'unit-existing-key','deepinfra_image_model':'PrunaAI/p-image'}
    params=VideoParams(video_subject='Existing video pipeline',video_aspect='16:9')
    with patch.object(api.requests,'Session',return_value=client):
        output,details=api.generate(params,'A documentary steam locomotive, no text.',tmp_path/'scene',settings=settings)
        recovered,_=api.generate(params,'A documentary steam locomotive, no text.',tmp_path/'scene',settings=settings,existing_only=True)
    client.post.assert_called_once()
    assert client.post.call_args.args==('https://api.deepinfra.com/v1/openai/images/generations',)
    sent=client.post.call_args.kwargs
    assert sent['headers']=={'Authorization':'Bearer unit-existing-key'}
    assert sent['json']==dict(model='PrunaAI/p-image',prompt='A documentary steam locomotive, no text.',n=1,size='1024x576',response_format='b64_json')
    assert sent['allow_redirects'] is False
    with Image.open(output) as image:
        assert image.format=='PNG' and image.size==(1024,576) and image.mode=='RGB'
        image.verify()
    assert recovered==output and details['model']=='PrunaAI/p-image'
    ledger=(tmp_path/'scene/deepinfra-image.json').read_text()
    assert json.loads(ledger)['status']=='saved'
    assert 'unit-existing-key' not in ledger+caplog.text


@pytest.mark.parametrize('encoded',['%%%bad',base64.b64encode(b'not-image').decode()])
def test_invalid_base64_or_image_is_reported_without_second_request(tmp_path,encoded):
    post=Mock(return_value=json.dumps({'data':[{'b64_json':encoded}]}).encode())
    params=VideoParams(video_subject='Test',video_aspect='16:9',deepinfra_model='PrunaAI/p-image')
    with patch.object(api,'_post',post):
        for _ in range(2):
            with pytest.raises(api.DeepInfraError,match='Resposta DeepInfra salva inválida'):
                api.generate(params,'Scene',tmp_path/'scene',settings={'deepinfra_api_key':'unit-key'})
    post.assert_called_once()


@pytest.mark.parametrize('status',[401,403,429,422,503])
def test_p_image_errors_retain_http_status_and_never_retry(tmp_path,status):
    client=session_for(response(status,{'Retry-After':'60'}))
    params=VideoParams(video_subject='Test',deepinfra_model='PrunaAI/p-image')
    with patch.object(api.requests,'Session',return_value=client):
        with pytest.raises(api.DeepInfraHTTPError,match='HTTP '+str(status)):
            api.generate(params,'Scene',tmp_path/'scene',settings={'deepinfra_api_key':'unit-key'})
        with pytest.raises(api.DeepInfraError):
            api.generate(params,'Scene',tmp_path/'scene',settings={'deepinfra_api_key':'unit-key'})
    client.post.assert_called_once()
    assert json.loads((tmp_path/'scene/deepinfra-image.json').read_text())['http_status']==status


def test_catalog_ui_selects_p_image_and_existing_test_button_requests_one(tmp_path):
    image=tmp_path/'saved.png';image.write_bytes(base64.b64decode(encoded_image()))
    generate=Mock(return_value=(image,{'model':'PrunaAI/p-image','width':1024,'height':576}))
    with patch.object(api,'generate',generate):
        app=AppTest.from_string('from webui.deepinfra_settings import render\nrender({"deepinfra_api_key":"unit-key"},lambda *args:None)').run()
        app.selectbox(key='deepinfra_image_model_input').select('PrunaAI/p-image').run()
        assert not app.exception
        generate.assert_not_called()
        app.button(key='deepinfra_test_start').click().run()
        assert not app.exception
        generate.assert_called_once()
        params=generate.call_args.args[0]
        assert params.deepinfra_model=='PrunaAI/p-image' and params.video_aspect.value=='16:9'
    assert api.MODELS[api.FLUX_MODEL]=='DeepInfra — FLUX.1 Schnell'
    assert api.MODELS[api.MODEL]=='DeepInfra — SDXL Turbo'
    assert api.MODELS['PrunaAI/p-image']=='PrunaAI P-Image'
    assert api.model({})==api.FLUX_MODEL  # Existing default is preserved.


def test_saved_p_image_job_recovers_despite_current_model_change(tmp_path):
    raw=json.dumps({'data':[{'b64_json':encoded_image()}]}).encode()
    with patch.object(api,'_post',return_value=raw) as post:
        image,_=api.generate(VideoParams(video_subject='Test',video_aspect='16:9',deepinfra_model='PrunaAI/p-image'),'Scene',tmp_path/'scene',settings={'deepinfra_api_key':'unit-key'})
        restored=VideoParams(video_subject='Test',video_aspect='16:9')
        recovered,_=api.generate(restored,'Scene',tmp_path/'scene',settings={'deepinfra_api_key':'unit-key','deepinfra_image_model':api.FLUX_MODEL},existing_only=True)
    assert recovered==image and restored.deepinfra_model=='PrunaAI/p-image'
    post.assert_called_once()


def test_base64_jpeg_response_is_saved_as_png_and_opens_in_montage(tmp_path):
    import io
    from moviepy import ImageClip
    buffer=io.BytesIO()
    Image.new('RGB',(1024,576),'navy').save(buffer,format='JPEG')
    body={'data':[{'b64_json':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()}]}
    with patch.object(api,'_post',return_value=json.dumps(body).encode()) as post:
        path,details=api.generate(VideoParams(video_subject='Scene',video_aspect='16:9',deepinfra_model='PrunaAI/p-image'),
                                  'A documentary railway scene.',tmp_path/'scene',settings={'deepinfra_api_key':'unit-key'})
    post.assert_called_once()
    with Image.open(path) as decoded:
        assert decoded.format=='PNG' and decoded.size==(1024,576)
    with ImageClip(str(path)).with_duration(.1) as clip:
        assert clip.get_frame(0).shape==(576,1024,3)
    assert details['width']*9==details['height']*16
