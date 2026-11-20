import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
import requests
from app.services.ai33 import tts
from app.services.ai33.client import AI33Error,_TransientError
from app.services import voice,task
from app.models.schema import VideoParams
from app.config import config

VOICE='elevenlabs_testVoice123'
TASK='a2dd6e44-2914-4b90-a4d2-4ab35f577f3d'
TEXT='This is a short historical narration for an integration test.'
SRT=b'1\n00:00:00,100 --> 00:00:01,800\nThis is a short historical narration.\n'


@pytest.fixture
def audio_env(tmp_path,monkeypatch):
    source=tmp_path/'source.wav'
    subprocess.run([tts.utils.get_ffmpeg_binary(),'-nostdin','-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-y',str(source)],check=True,capture_output=True)
    raw=source.read_bytes();output=tmp_path/'project'/'audio.mp3'
    def download(url,target,limit):Path(target).write_bytes(SRT if url.endswith('.srt') else raw)
    monkeypatch.setattr(tts,'download',download)
    client=Mock();client.create.return_value=TASK
    client.speech_task.return_value={'id':TASK,'type':'v3_tts','status':'done','credit_cost':25,
        'metadata':{'audio_url':'https://cdn.ai33.pro/sound.mp3','srt_url':'https://cdn.ai33.pro/sound.srt'}}
    return output,client


def run(env,**kw):
    output,client=env
    return tts.synthesize(TEXT,VOICE,1.,output,client=client,settings={},**kw)


def test_validated_audio_captions_and_cache_never_repeat_paid_post(audio_env):
    output,client=audio_env;maker=run(audio_env)
    assert output.is_file() and voice.get_audio_duration(str(output))>1.9
    state=tts.load(tts.paths(output)[0])
    assert state['phase']=='completed' and state['task_id']==TASK and state['actual_credits']==25
    assert state['audio_sha256']==tts.checksum(output)
    assert tts.transcript_for(output,maker)==SRT
    second=run(audio_env)
    assert second.duration==maker.duration and client.create.call_count==1 and client.speech_task.call_count==1
    assert 'https://' not in json.dumps(state) and TEXT not in json.dumps(state)


def test_doing_timeout_then_resume_same_id(audio_env):
    output,client=audio_env
    done=client.speech_task.return_value
    client.speech_task.return_value={'id':TASK,'type':'v3_tts','status':'doing','progress':50}
    with pytest.raises(AI33Error,match='ID foi salvo'):run(audio_env,wait_seconds=0)
    client.speech_task.return_value=done
    assert run(audio_env).duration>0
    client.create.assert_called_once()


def test_ambiguous_post_is_never_retried(audio_env):
    output,client=audio_env;client.create.side_effect=requests.Timeout('SECRET_KEY')
    with pytest.raises(AI33Error,match='não confirmou'):run(audio_env)
    with pytest.raises(AI33Error,match='sem ID'):run(audio_env)
    assert client.create.call_count==1 and 'SECRET_KEY' not in tts.paths(output)[0].read_text()


def test_failed_download_resumes_without_new_post(audio_env,monkeypatch):
    output,client=audio_env;download=tts.download
    monkeypatch.setattr(tts,'download',Mock(side_effect=AI33Error('interrupted download')))
    with pytest.raises(AI33Error):run(audio_env)
    monkeypatch.setattr(tts,'download',download)
    assert run(audio_env).duration>0
    client.create.assert_called_once()


def test_missing_audio_is_downloaded_again_from_same_task(audio_env):
    output,client=audio_env;run(audio_env);output.unlink()
    assert run(audio_env).duration>0
    client.create.assert_called_once()
    assert client.speech_task.call_count==2


@pytest.mark.parametrize('change',['text','voice','speed','audio'])
def test_changed_job_never_submits_second_generation(audio_env,change):
    output,client=audio_env;run(audio_env)
    if change=='audio':output.write_bytes(b'changed')
    with pytest.raises(AI33Error):
        tts.synthesize(TEXT+' changed' if change=='text' else TEXT,'edge_en-US-AriaNeural' if change=='voice' else VOICE,
            1.2 if change=='speed' else 1.,output,client=client,settings={})
    client.create.assert_called_once()


def test_invalid_audio_does_not_replace_existing_file_or_resubmit(audio_env,monkeypatch):
    output,client=audio_env;output.parent.mkdir();output.write_bytes(b'previous audio')
    monkeypatch.setattr(tts,'download',lambda url,target,limit:Path(target).write_bytes(b'not real audio'))
    for _ in range(2):
        with pytest.raises(AI33Error,match='inválido'):run(audio_env)
    assert output.read_bytes()==b'previous audio'
    client.create.assert_called_once()


def test_transcript_times_must_match_real_audio():
    for raw in [b'<html>blocked</html>',b'1\n00:00:03,000 --> 00:00:02,000\nBad',b'1\n00:00:00,000 --> 00:00:09,000\nBad']:
        with pytest.raises(AI33Error):tts.srt_content(raw,2.)


def test_bad_transcript_does_not_invent_timing(audio_env,monkeypatch):
    output,client=audio_env;download=tts.download
    def bad(url,target,limit):
        if url.endswith('.srt'):Path(target).write_bytes(b'<html>bad</html>')
        else:download(url,target,limit)
    monkeypatch.setattr(tts,'download',bad)
    maker=run(audio_env)
    assert not maker.cues and not maker.offset and tts.transcript_for(output,maker) is None
    assert tts.load(tts.paths(output)[0])['transcript_status']=='unavailable_or_invalid'


def test_dispatch_uses_ai33_and_pause_tags_do_not_split_paid_calls(tmp_path):
    maker=object()
    with patch.object(tts,'synthesize',return_value=maker) as synth:
        assert voice.tts('Hello [pause: 1s] world','ai33:'+VOICE,1.,str(tmp_path/'audio.mp3')) is maker
        synth.assert_called_once()
        assert not voice.is_azure_v1_voice('ai33:'+VOICE)
        assert voice.parse_voice_name('ai33:'+VOICE)=='ai33:'+VOICE


def test_actual_ai33_srt_flows_to_task_without_whisper(audio_env,monkeypatch):
    output,client=audio_env;maker=run(audio_env)
    monkeypatch.setattr(task.utils,'task_dir',lambda *a,**kw:str(output.parent))
    monkeypatch.setitem(config.app,'subtitle_provider','edge')
    params=VideoParams(video_subject='Test',voice_name='ai33:'+VOICE)
    with patch.object(task.subtitle,'create') as whisper:
        path=task.generate_subtitle('project',params,TEXT,maker,str(output))
        assert Path(path).read_bytes()==SRT
        whisper.assert_not_called()


def test_preview_can_be_adopted_without_losing_task_id(audio_env):
    output,client=audio_env;maker=run(audio_env)
    new=output.parent.parent/'another-project'/'audio.mp3';new.parent.mkdir();new.write_bytes(output.read_bytes())
    tts.adopt_preview(new,maker)
    assert tts.load(tts.paths(new)[0])['task_id']==TASK
    assert tts.transcript_for(new,maker)==SRT
    tts.synthesize(TEXT,VOICE,1.,new,client=client,settings={})
    client.create.assert_called_once()


def test_budget_and_speed_checked_before_any_paid_call(audio_env):
    output,client=audio_env
    with pytest.raises(AI33Error,match='velocidade'):tts.synthesize(TEXT,VOICE,2.,output,client=client)
    with pytest.raises(AI33Error,match='teto local'):tts.synthesize(TEXT*100,VOICE,1.,output,client=client,settings={'ai33_tts_max_characters':100})
    client.create.assert_not_called()


def test_http_contract_multipart_single_post_and_task_identity():
    client=tts.SpeechClient('PRIVATE_API_KEY')
    with patch.object(client,'_request',return_value={'success':True,'task_id':TASK}) as request:
        assert client.create(TEXT,VOICE,1.)==TASK
        assert request.call_args.args==('POST','/v3/text-to-speech')
        assert dict(request.call_args.kwargs['files'])['with_transcript']==(None,'true')
        assert 'PRIVATE_API_KEY' not in str(request.call_args.kwargs)
    with patch.object(client,'_request',return_value={'id':TASK,'type':'imagen2','status':'done'}):
        with pytest.raises(AI33Error):client.speech_task(TASK)


def test_download_never_forwards_api_key(tmp_path,monkeypatch):
    response=Mock(status_code=200,headers={});response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
    response.iter_content.return_value=[b'data']
    monkeypatch.setattr(tts,'_public_https',lambda url:None)
    with patch.object(tts.requests,'get',return_value=response) as get:
        tts.download('https://cdn.ai33.pro/audio.mp3',tmp_path/'a.bin',100)
    assert 'headers' not in get.call_args.kwargs and get.call_args.kwargs['allow_redirects'] is False
