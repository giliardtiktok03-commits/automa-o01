import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from app.models.schema import VideoParams
from app.services import mixed_resume as resume, task, material

ID = '5c8b2e2a-3360-449a-a84d-297f6ab90bcf'


@pytest.fixture
def saved_project(tmp_path, monkeypatch):
    def task_dir(task_id=''):
        directory=tmp_path/task_id
        directory.mkdir(exist_ok=True,parents=True)
        return str(directory)
    monkeypatch.setattr(resume.utils,'task_dir',task_dir)
    directory=Path(task_dir(ID))
    audio=directory/'custom-audio.mp3'
    audio.write_bytes(b'original audio')
    params=VideoParams(video_subject='history',video_script='Original script.',video_source='mixed',
                       subtitle_enabled=False,custom_audio_file=str(audio))
    task.save_script_data(ID,params.video_script,[],params)
    manifest={'image_requests':12,'scenes':[{'id':1,'start_frame':0,'end_frame':900,'text':'Original script.'}]}
    (directory/'mixed-scenes.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(resume.voice,'get_audio_duration',lambda *_:30)
    requests=Mock()
    monkeypatch.setattr(material,'generate_images_openai',requests)
    return directory,manifest,requests


def test_unknown_paid_request_is_blocked_without_resubmission(saved_project):
    directory,manifest,requests=saved_project
    manifest['scenes'][0]['image_request_started']=True
    (directory/'mixed-scenes.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='unknown result'):
        resume.load(ID,24)
    requests.assert_not_called()


def test_lower_total_budget_does_not_reset_started_count(saved_project):
    _,_,requests=saved_project
    with pytest.raises(ValueError,match='below requests'):
        resume.load(ID,11)
    requests.assert_not_called()


def test_missing_audio_does_not_trigger_tts(saved_project,monkeypatch):
    directory,_,requests=saved_project
    (directory/'custom-audio.mp3').unlink()
    tts=Mock()
    monkeypatch.setattr(task,'generate_audio',tts)
    with pytest.raises(ValueError,match='missing'):
        resume.load(ID,24)
    tts.assert_not_called()
    requests.assert_not_called()


def test_media_changes_after_checkpoint_are_blocked(saved_project):
    directory,_,requests=saved_project
    (directory/'resume-media.json').write_text(json.dumps({'audio':hashlib.sha256(b'old').hexdigest(),'subtitle':None}))
    with pytest.raises(ValueError,match='changed'):
        resume.load(ID,24)
    requests.assert_not_called()
