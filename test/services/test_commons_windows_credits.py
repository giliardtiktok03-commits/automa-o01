"""Replay Windows-style saved audit paths, safely finish credits without redoing media."""
import json
import ntpath
from pathlib import PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from PIL import Image
from app.models.schema import VideoParams
from app.services.historical_archive import commons_credits as credits, commons_probe as probe, manifest
from app.services.historical_archive.contracts import ArchiveError
from test.services.test_commons_license_manager import commons


@pytest.fixture
def saved(tmp_path,monkeypatch):
    monkeypatch.setattr(probe.utils,'storage_dir',lambda:str(tmp_path))
    task_id='commons-test-'+uuid4().hex
    folder=probe.folder(task_id);folder.mkdir(parents=True)
    source=folder/'scene_001'/'approved'/'original.png';source.parent.mkdir(parents=True)
    Image.new('RGB',(160,90),'blue').save(source)
    clip=folder/'commons-test-clip.mp4';clip.write_bytes(b'already decoded clip retained for recovery fixture')
    c=commons('by')
    row={'id':'candidate1','candidate':c.to_dict(),'used':True,'rights_status':'rights_cleared',
        'downloaded_file':r'scene_001\approved\original.png','sha256':credits.digest(source),
        'commons_render_use':{'render_file':r'historical_archive\commons-test-clip.mp4',
            'render_sha256':credits.digest(clip),'modifications':['Converted to RGB PNG','Static 16:9 clip']}}
    manifest.save(folder,{'version':1,'scenes':{'scene_001':{'candidates':[row]}},'providers':{},'downloads':{}})
    probe.save(task_id,{'task_id':task_id,'state':'failed','error':'Previous generic failure','published':False,
        'query':'World War II aircraft 1943','clip':{'file':clip.name,'sha256':credits.digest(clip),'decode_verified':True},
        'download':{'file':row['downloaded_file'],'sha256':row['sha256']},
        'candidates':[{'candidate':c.to_dict(),'classification':'AUTO_APPROVED','used_in_test':False}]})
    return task_id,folder,source,clip


def test_repair_windows_saved_paths_creates_both_missing_reports_without_network_or_render(saved,monkeypatch):
    task_id,folder,source,clip=saved
    network=Mock(side_effect=AssertionError('No new request'));render=Mock(side_effect=AssertionError('No rerender'))
    from app.services.historical_archive import network as transport
    monkeypatch.setattr(transport.requests,'get',network);monkeypatch.setattr(probe,'render_clip',render)
    before=(credits.digest(source),credits.digest(clip))
    report=probe.repair_credits(task_id)
    assert report['state']=='completed' and not report['published']
    assert report['candidates'][0]['used_in_test'] and 'error' not in report
    assert 'Historical Image Credits' in (folder/'youtube-description-with-credits.txt').read_text()
    assert json.loads((folder/'commons-publication-review.json').read_text())['status']=='ready_for_manual_publication'
    record=next(iter(json.loads((folder/'commons-final-media.json').read_text())['videos'].values()))
    assert record['bindings'][0]['render_file']=='historical_archive/commons-test-clip.mp4'
    assert before==(credits.digest(source),credits.digest(clip))
    assert probe.repair_credits(task_id)['description_with_credits']==report['description_with_credits']
    network.assert_not_called();render.assert_not_called()


@pytest.mark.parametrize('changed',['image','clip'])
def test_repair_never_credits_changed_saved_files(saved,changed):
    task_id,folder,source,clip=saved
    (source if changed=='image' else clip).write_bytes(b'changed')
    report=probe.repair_credits(task_id)
    assert report['state']=='failed' and not report['published']
    assert json.loads((folder/'commons-publication-review.json').read_text())['status']=='NEEDS_REVIEW'
    assert not (folder/'youtube-description-with-credits.txt').exists()


def test_unexpected_error_is_reported_without_exposing_exception_values(saved,monkeypatch):
    task_id,folder,_,_=saved
    monkeypatch.setattr(credits,'_bind_final',Mock(side_effect=KeyError('private value must not appear')))
    result=probe.repair_credits(task_id)
    technical=json.loads((folder/'commons-publication-review.json').read_text())
    assert result['state']=='failed' and technical['error_type']=='KeyError'
    assert 'private value' not in json.dumps(technical)
    assert technical['technical_frames'] and not technical['published']


@pytest.mark.parametrize('name',[r'C:\outside\video.mp4','C:/outside/video.mp4',r'..\config.toml','../config.toml',r'\\server\share\file','image.png:stream'])
def test_portable_path_support_does_not_allow_absolute_paths_or_escape(name):
    with pytest.raises(ArchiveError):credits.relative_name(name)


def test_windows_path_identity_is_case_insensitive_without_string_comparisons(monkeypatch):
    first=PureWindowsPath('C:/MPT/historical_archive/clip.mp4')
    second=PureWindowsPath('c:/mpt/Historical_Archive/clip.mp4')
    assert first==second and str(first)!=str(second)
    monkeypatch.setattr(credits,'os',SimpleNamespace(path=ntpath))
    assert credits.path_key(r'Historical_Archive\Clip.mp4')==credits.path_key('historical_archive/clip.mp4')


def test_saved_report_button_appears_and_submits_repair(saved,monkeypatch):
    from streamlit.testing.v1 import AppTest
    task_id,_,_,_=saved
    repair=Mock(return_value=task_id);monkeypatch.setattr(probe,'submit_repair',repair)
    app=AppTest.from_string('from webui.commons_probe import render\nrender()').run()
    assert not app.exception
    app.button(key='commons_probe_repair').click().run()
    assert not app.exception
    repair.assert_called_once_with(task_id)
