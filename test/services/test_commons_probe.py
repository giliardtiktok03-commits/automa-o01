"""Standalone Commons test stays independent from production settings and providers."""
import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest
from app.services.historical_archive import commons_probe as probe
from app.services.historical_archive.contracts import ArchiveCandidate
from app.config import config
from test.services.test_wikimedia_commons import record


@pytest.fixture
def root(tmp_path,monkeypatch):
    monkeypatch.setattr(probe.utils,'storage_dir',lambda:str(tmp_path))
    return tmp_path


def test_render_has_no_network_or_submission_and_works_with_archives_off(root,monkeypatch):
    submit=Mock();monkeypatch.setattr(probe,'submit',submit)
    app=AppTest.from_string('from webui.commons_probe import render\nrender()').run()
    assert not app.exception
    assert app.text_input(key='commons_probe_query').value=='World War II aircraft 1943'
    assert not app.button(key='commons_probe_start').disabled
    submit.assert_not_called()


def test_click_submits_only_once_with_explicit_clip_option(root,monkeypatch):
    task_id='commons-test-'+uuid4().hex
    probe.save(task_id,{'state':'queued','stage':'Test queued'})
    submit=Mock(return_value=task_id);monkeypatch.setattr(probe,'submit',submit)
    app=AppTest.from_string('from webui.commons_probe import render\nrender()').run()
    app.checkbox(key='commons_probe_clip').uncheck()
    app.button(key='commons_probe_start').click().run()
    assert not app.exception
    submit.assert_called_once_with('World War II aircraft 1943',False)
    app.button(key='commons_probe_refresh').click().run()
    assert submit.call_count==1


def test_probe_filters_by_sa_and_special_notices_without_touching_shared_policy():
    raw=record('CC BY-SA 4.0','Creative Commons Attribution-Share Alike')['query']['pages']['2110142']
    c=ArchiveCandidate(provider='wikimedia',record_id='1',title='Aircraft 1943',
        creator='Author',attribution='Author credit',rights_statement='CC BY-SA 4.0',
        license_url='https://creativecommons.org/licenses/by-sa/4.0/',metadata={'record':raw})
    assert probe.decision(c)[0]=='NEEDS_REVIEW'
    c.rights_statement='Public domain';c.license_url=''
    raw['imageinfo'][0]['extmetadata']['Restrictions']={'value':'Personality rights notice'}
    assert probe.decision(c)[0]=='NEEDS_REVIEW'
    c.rights_statement='Non-commercial only'
    assert probe.decision(c)[0]=='REJECTED'


def test_failed_network_is_saved_as_diagnostic_without_changing_settings(root,monkeypatch):
    from app.services.historical_archive.contracts import ArchiveError
    original=dict(config.app)
    def fail(*args,**kwargs):raise ArchiveError('Provider HTTP 403; sem contorno')
    monkeypatch.setattr(probe.WikimediaProvider,'search',fail)
    task_id='commons-test-'+uuid4().hex
    result=probe.run(task_id,'World War II aircraft 1943')
    assert result['state']=='failed' and '403' in result['error']
    assert not result['published'] and probe.read(task_id)==result
    assert probe.latest()==task_id and dict(config.app)==original


def test_real_local_clip_decode_has_expected_resolution(root):
    from PIL import Image
    source=root/'fixture.png';Image.new('RGB',(320,180),'blue').save(source)
    result=probe.render_clip(str(source),root/'fixture.mp4')
    assert result['decode_verified'] and result['width']==1920 and result['height']==1080
    assert 3.85<=result['duration']<=4.15


def test_artifacts_cannot_escape_test_folder(root):
    task_id='commons-test-'+uuid4().hex
    probe.save(task_id,{'state':'queued'})
    assert probe.artifact(task_id,'commons-test.json').is_file()
    with pytest.raises(ValueError):probe.artifact(task_id,'../../config.toml')
    with pytest.raises(ValueError):probe.folder('../task')
