import base64
import io
import json
from unittest.mock import Mock, patch

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app.models.schema import VideoParams
from app.services import deepinfra_image as api


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(api.config, 'app', {'deepinfra_api_key': 'secret-test-key'})
    out = io.BytesIO()
    Image.new('RGB', (256, 256), 'blue').save(out, format='PNG')
    payload = {'images':['data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()],
               'nsfw_content_detected':[False], 'request_id':'remote-1', 'inference_status':{'cost':0.001}}
    post = Mock(return_value=json.dumps(payload).encode())
    monkeypatch.setattr(api, '_post', post)
    return VideoParams(video_subject='History',video_aspect='16:9'), post, payload


def test_single_submission_cache_and_fingerprint(setup, tmp_path):
    params, post, _ = setup
    before = Mock()
    image, details = api.generate(params, 'Historical scene', tmp_path, before_submit=before)
    assert api.generate(params, 'Historical scene', tmp_path, existing_only=True)[0] == image
    post.assert_called_once()
    assert post.call_args.args[0] == dict(prompt='Historical scene',num_images=1,width=1024,height=576,num_inference_steps=1,guidance_scale=0)
    before.assert_called_once()
    assert details['request_id'] == 'remote-1'
    assert 'secret-test-key' not in (tmp_path/'deepinfra-image.json').read_text()
    assert Image.open(image).size == (256,256)
    with pytest.raises(api.DeepInfraError, match='diferem'):
        api.generate(params, 'Different scene', tmp_path)
    assert post.call_count == 1


@pytest.mark.parametrize('aspect,size', [('16:9',(1024,576)),('9:16',(576,1024)),('1:1',(512,512))])
def test_aspect_ratios(setup,tmp_path,aspect,size):
    params, post, _ = setup
    params.video_aspect = aspect
    api.generate(params,'Scene',tmp_path)
    body = post.call_args.args[0]
    assert (body['width'], body['height']) == size


def test_timeout_never_reposts_and_sanitizes_error(setup,tmp_path):
    params, post, _ = setup
    post.side_effect = RuntimeError('secret-test-key')
    with pytest.raises(api.DeepInfraError, match='sem reenvio') as error:
        api.generate(params,'Scene',tmp_path)
    assert 'secret-test-key' not in str(error.value)
    with pytest.raises(api.DeepInfraError, match='não confirmado'):
        api.generate(params,'Scene',tmp_path)
    post.assert_called_once()


def test_recovery_from_raw_response_does_not_submit(setup,tmp_path):
    params,post,payload = setup
    post.return_value = b'not-json'
    with pytest.raises(api.DeepInfraError, match='inválida'):
        api.generate(params,'Scene',tmp_path)
    (tmp_path/'response.json').write_text(json.dumps(payload))
    api.generate(params,'Scene',tmp_path,existing_only=True)
    post.assert_called_once()


def test_moderation_refusal_persists_without_rewording(setup,tmp_path):
    params,post,payload = setup
    payload['nsfw_content_detected'] = [True]
    post.return_value = json.dumps(payload).encode()
    for _ in range(2):
        with pytest.raises(api.DeepInfraRefusal):
            api.generate(params,'Scene',tmp_path)
    post.assert_called_once()


def test_missing_checkpoint_cannot_submit_on_recovery(setup,tmp_path):
    params,post,_ = setup
    with pytest.raises(api.DeepInfraError, match='ausente'):
        api.generate(params,'Scene',tmp_path,existing_only=True)
    post.assert_not_called()


def test_official_http_contract_has_no_retry_or_redirect():
    response = Mock(status_code=503)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.post.return_value = response
    with patch.object(api.requests,'Session', return_value=session):
        with pytest.raises(api.DeepInfraError, match='HTTP 503'):
            api._post({'prompt':'Scene'}, 'secret-test-key', 180)
    session.post.assert_called_once()
    assert session.post.call_args.args == ('https://api.deepinfra.com/v1/inference/stabilityai/sdxl-turbo',)
    assert session.post.call_args.kwargs['headers']['Authorization'] == 'Bearer secret-test-key'
    assert session.post.call_args.kwargs['allow_redirects'] is False


def test_ui_masks_key_and_never_generates_on_render():
    with patch.object(api,'generate') as generate:
        app=AppTest.from_string('from webui.deepinfra_settings import render\nrender({"deepinfra_api_key":"local-key"},lambda *args:None)').run()
        assert not app.exception
        assert app.text_input(key='deepinfra_image_api_key_input').proto.type == 1
        generate.assert_not_called()
