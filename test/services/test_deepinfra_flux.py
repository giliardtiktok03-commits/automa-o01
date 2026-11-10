import base64
import io
import json
import os
from unittest.mock import Mock, patch
import pytest
from PIL import Image, ImageDraw
from streamlit.testing.v1 import AppTest
from app.models.schema import VideoParams
from app.services import deepinfra_image as api


@pytest.fixture(autouse=True)
def isolated_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(api, '_rate_file', lambda key: tmp_path / 'rate.json')


def encoded_image():
    out=io.BytesIO()
    image=Image.new('RGB',(800,400),'white')
    ImageDraw.Draw(image).ellipse((300,100,500,300),fill='red')
    image.save(out,format='PNG')
    return base64.b64encode(out.getvalue()).decode()


def response(status=200,headers=None,data=None):
    value=Mock(status_code=status,headers=headers or {})
    value.__enter__=Mock(return_value=value)
    value.__exit__=Mock(return_value=None)
    value.iter_content.return_value=[json.dumps(data or {'data':[{'b64_json':encoded_image()}]}).encode()]
    return value


def session_for(value):
    client=Mock()
    client.__enter__=Mock(return_value=client)
    client.__exit__=Mock(return_value=None)
    client.post.return_value=value
    return client


def test_flux_real_http_contract_base64_cache_no_key_in_logs(tmp_path,monkeypatch,caplog):
    monkeypatch.setenv('DEEPINFRA_API_KEY','unit-private-key')
    monkeypatch.setenv('DEEPINFRA_IMAGE_MODEL',api.FLUX_MODEL)
    client=session_for(response())
    with patch.object(api.requests,'Session',return_value=client):
        params=VideoParams(video_subject='Illustration',video_aspect='16:9')
        image,details=api.generate(params,'A submarine at sea',tmp_path/'job',settings={})
        assert api.generate(params,'A submarine at sea',tmp_path/'job',settings={},existing_only=True)[0]==image
    client.post.assert_called_once()
    assert client.post.call_args.args==(api.FLUX_ENDPOINT,)
    sent=client.post.call_args.kwargs
    assert sent['json']=={'model':api.FLUX_MODEL,'prompt':'A submarine at sea','n':1,'size':'1024x576','response_format':'b64_json'}
    assert sent['headers']=={'Authorization':'Bearer unit-private-key'}
    assert sent['timeout']==(15,180) and sent['allow_redirects'] is False
    assert Image.open(image).size==(1024,576)
    assert details['model']==api.FLUX_MODEL
    assert 'unit-private-key' not in caplog.text
    assert 'unit-private-key' not in (tmp_path/'job/deepinfra-image.json').read_text()


@pytest.mark.parametrize('value', ['%%%invalid','data:text/plain;base64,YWJj',base64.b64encode(b'not an image').decode()])
def test_invalid_base64_or_image_never_triggers_new_generation(tmp_path,value):
    post=Mock(return_value=json.dumps({'data':[{'b64_json':value}]}).encode())
    params=VideoParams(video_subject='Test',video_aspect='16:9',deepinfra_model=api.FLUX_MODEL)
    with patch.object(api,'_post',post):
        for _ in range(2):
            with pytest.raises(api.DeepInfraError,match='inválida'):
                api.generate(params,'Scene',tmp_path/'job',settings={'deepinfra_api_key':'test-key'})
    post.assert_called_once()


@pytest.mark.parametrize('status',[401,403,429,503])
def test_http_errors_safe_and_never_repost(tmp_path,status):
    client=session_for(response(status,{'Retry-After':'120'}))
    params=VideoParams(video_subject='Test',deepinfra_model=api.FLUX_MODEL)
    with patch.object(api.requests,'Session',return_value=client):
        with pytest.raises(api.DeepInfraHTTPError,match=f'HTTP {status}'):
            api.generate(params,'Scene',tmp_path/'job',settings={'deepinfra_api_key':'unit-key'})
        with pytest.raises(api.DeepInfraError):
            api.generate(params,'Scene',tmp_path/'job',settings={'deepinfra_api_key':'unit-key'})
        if status==429:
            with pytest.raises(api.DeepInfraError,match='espera'):
                api.generate(params,'Other scene',tmp_path/'another-job',settings={'deepinfra_api_key':'unit-key'})
    client.post.assert_called_once()
    ledger=json.loads((tmp_path/'job/deepinfra-image.json').read_text())
    assert ledger['http_status']==status
    assert 'unit-key' not in json.dumps(ledger)


def test_url_response_uses_existing_public_https_download_without_credentials(tmp_path):
    raw=json.dumps({'data':[{'url':'https://images.example.test/result.png'}]}).encode()
    with patch.object(api,'_post',return_value=raw), patch('app.services.ai33.images.download_png',return_value=base64.b64decode(encoded_image())) as download:
        image,_=api.generate(VideoParams(video_subject='Test',deepinfra_model=api.FLUX_MODEL),'Scene',tmp_path/'job',settings={'deepinfra_api_key':'secret'})
        assert Image.open(image).size==(576,1024)  # default portrait
        download.assert_called_once_with('https://images.example.test/result.png')


def test_old_sdxl_checkpoint_recovers_with_new_default_flux(tmp_path):
    params=VideoParams(video_subject='Test',video_aspect='16:9',deepinfra_model=api.MODEL)
    post=Mock(return_value=json.dumps({'images':[encoded_image()]}).encode())
    with patch.object(api,'_post',post):
        image,_=api.generate(params,'Scene',tmp_path/'job',settings={'deepinfra_api_key':'key'})
        path=tmp_path/'job/deepinfra-image.json'
        state=json.loads(path.read_text());state['version']=1;state.pop('model');path.write_text(json.dumps(state))
        recovered,_=api.generate(VideoParams(video_subject='Test',video_aspect='16:9'),'Scene',tmp_path/'job',settings={'deepinfra_api_key':'key','deepinfra_image_model':api.FLUX_MODEL},existing_only=True)
        assert recovered==image
        post.assert_called_once()


def test_thumbnail_disabled_does_not_call_api_and_enabled_preserves_shapes(tmp_path):
    with patch.object(api,'_post') as post:
        with pytest.raises(api.DeepInfraError,match='Ative'):
            api.generate_thumbnail('Scene',tmp_path/'off',settings={})
        post.assert_not_called()
    with patch.object(api,'_post',return_value=json.dumps({'data':[{'b64_json':encoded_image()}]}).encode()) as post:
        image,_=api.generate_thumbnail('Scene',tmp_path/'on',settings={'deepinfra_api_key':'key','deepinfra_thumbnails_enabled':True,'deepinfra_image_model':api.FLUX_MODEL})
        with Image.open(image) as output:
            assert output.size==(1280,720)
            pixels=output.load()
            xs,ys=[],[]
            for y in range(output.height):
                for x in range(output.width):
                    r,g,b=pixels[x,y]
                    if r>180 and g<60 and b<60:xs.append(x);ys.append(y)
            assert abs((max(xs)-min(xs))-(max(ys)-min(ys)))<=2
        post.assert_called_once()


def test_ui_test_and_thumbnail_only_run_on_explicit_click(tmp_path,monkeypatch):
    result=tmp_path/'image.png';result.write_bytes(base64.b64decode(encoded_image()))
    with patch.object(api,'generate',return_value=(result,{'model':api.FLUX_MODEL})) as generate, patch.object(api,'generate_thumbnail',return_value=(result,{})) as thumb:
        app=AppTest.from_string('from webui.deepinfra_settings import render\nrender({"deepinfra_api_key":"local-key"},lambda *args:None)').run()
        assert not app.exception
        assert app.selectbox(key='deepinfra_image_model_input').value==api.FLUX_MODEL
        assert app.button(key='deepinfra_test_start').label=='Testar DeepInfra'
        generate.assert_not_called();thumb.assert_not_called()
        app.button(key='deepinfra_test_start').click().run()
        assert not app.exception and generate.call_count==1
        assert app.get('imgs') or app.session_state['deepinfra_test_result']
        app.checkbox(key='deepinfra_thumbnails_enabled').check().run()
        thumb.assert_not_called()
        app.button(key='deepinfra_thumbnail_generate').click().run()
        assert not app.exception and thumb.call_count==1


def test_live_deepinfra_flux_when_credentials_configured(tmp_path):
    if os.environ.get('MPT_DEEPINFRA_LIVE_TESTS')!='1':pytest.skip('Opt-in paid image generation test')
    if not api.api_key():pytest.skip('DeepInfra credentials not configured; no real image request sent')
    image,details=api.generate(VideoParams(video_subject='Live test',video_aspect='16:9',deepinfra_model=api.FLUX_MODEL),'A realistic documentary photograph of a steam locomotive, wide composition, no text.',tmp_path/'live')
    with Image.open(image) as decoded:assert decoded.size==(1024,576)
    assert details['model']==api.FLUX_MODEL
