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
        resume.load(ID,11,grok_unlimited=False)
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


def test_unlimited_resume_ignores_old_total_cap_but_keeps_started_count(saved_project,monkeypatch):
    from app.config import config
    directory,manifest,requests=saved_project
    monkeypatch.setattr(config,'ui',{'mixed_use_grok':True})
    manifest['image_requests']=130
    (directory/'mixed-scenes.json').write_text(json.dumps(manifest))
    project=resume.load(ID,0,grok_unlimited=True)
    assert project['started']==130 and project['params'].mixed_grok_unlimited
    requests.assert_not_called()
    with pytest.raises(ValueError,match='below requests'):
        resume.load(ID,0,grok_unlimited=False)


def test_resume_applies_explicit_subtitle_style_without_regenerating_audio(saved_project,monkeypatch):
    from app.services import subtitle_style
    directory,manifest,requests=saved_project
    script_file=directory/'script.json'
    saved=json.loads(script_file.read_text())
    saved['params']['subtitle_enabled']=True
    script_file.write_text(json.dumps(saved))
    (directory/'subtitle.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nOriginal script.\n',encoding='utf-8')
    monkeypatch.setattr(resume.mixed_materials,'prepare',lambda *args,**kwargs:['saved-clip.mp4'])
    def render(task_id,params,materials,audio,subtitles,duration):
        assert params.font_name=='Montserrat-ExtraBold.ttf' and params.font_size==60
        assert params.stroke_width==4 and params.subtitle_soft_shadow and params.subtitle_max_lines==2
        assert materials==['saved-clip.mp4'] and audio==str(directory/'custom-audio.mp3')
        assert subtitles==str(directory/'subtitle.srt')
        target=directory/'final-1.mp4'
        target.write_bytes(b'finished')
        return [str(target)],[],[]
    monkeypatch.setattr(task,'generate_final_videos',render)
    tts=Mock(side_effect=AssertionError('Narration must be reused'))
    monkeypatch.setattr(task,'generate_audio',tts)
    result=resume.run(ID,24,subtitle_settings=subtitle_style.DOCUMENTARY)
    assert result['videos']
    tts.assert_not_called()
    requests.assert_not_called()
