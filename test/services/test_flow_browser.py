import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from PIL import Image
from app.services import flow_browser as flow

URL = 'https://flow.google.com/project/39a3cd68-17c5-4695-8c99-52ea21b38e66'


@pytest.mark.parametrize('profile,url', [('..',URL), ('a/b',URL), ('principal','https://evil.test/project/a'),
                                      ('principal', URL+'?token=private'), ('principal','http://flow.google.com/project/a')])
def test_profile_and_project_are_restricted(profile, url):
    with pytest.raises(ValueError):
        flow.validate(profile, url)


def test_missing_optional_dependency_is_reported_before_browser_launch(monkeypatch):
    monkeypatch.setattr(flow.importlib.util, 'find_spec', lambda *_: None)
    with pytest.raises(flow.FlowError, match='PREPARAR_FLOW_WINDOWS'):
        flow.validate('principal', URL)


@pytest.mark.parametrize('status', ['ready', 'refused', 'cancelled'])
def test_handoff_is_single_request_and_never_retries(tmp_path, monkeypatch, status):
    monkeypatch.setattr(flow, 'validate', lambda *_: None)
    def launch(file):
        body = json.loads(file.read_text())
        assert body['project'] == URL and body['profile'] == 'principal'
        assert not any(k in body for k in ('password','cookie','token'))
        if status == 'ready':
            Image.new('RGB', (64,64), 'blue').save(file.with_suffix('.png'))
        file.with_suffix('.result.json').write_text(json.dumps({'status':status}))
        return Mock()
    launcher = Mock(side_effect=launch)
    monkeypatch.setattr(flow, '_launch', launcher)
    if status == 'ready':
        assert flow.generate('A historical illustration', tmp_path, 'principal', URL).is_file()
    else:
        with pytest.raises(flow.FlowError):
            flow.generate('A historical illustration', tmp_path, 'principal', URL)
    assert launcher.call_count == 1


def test_download_is_decoded_not_trusted_by_extension(tmp_path):
    def save(path):
        Path(path).write_text('not an image')
    with pytest.raises(Exception):
        flow._save_image(Mock(save_as=save), tmp_path/'image.png')
    assert not (tmp_path/'image.png').exists()
    assert not (tmp_path/'image.download').exists()
