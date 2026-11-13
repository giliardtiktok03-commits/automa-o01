"""Offline production bridge: frozen settings, durable stages and real FFmpeg QA."""
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from app.models.historical_director import Request, VideoProduction
from app.services.historical_director import video_production as bridge, production
from app.services.autopilot.recovery import RecoveryBlocked
from app.services.autopilot.repository import Repository
from app.services.autopilot import worker
from app.services import task, voice, mixed_resume, webui_task
from app.config import config
from test.services.test_historical_director_queue import setup, analyzed


def job(setup,monkeypatch,mode='video'):
    repo,snapshot=setup
    root=Path(production.utils.task_dir())
    def task_dir(task_id=''):
        path=root/task_id
        path.mkdir(parents=True,exist_ok=True)
        return str(path)
    monkeypatch.setattr(bridge.utils,'task_dir',task_dir)
    batch,_=analyzed(setup,production=VideoProduction(mode=mode,subtitle_enabled=False))
    ids,_=repo.enqueue_director_angles(batch,['angle_01'])
    pending=repo.take_editorial()
    assert pending['task_id']==ids[0]
    options=Request.model_validate(json.loads(repo.director_item(ids[0])['context'])['request']).production
    return repo,snapshot,ids[0],options


def make_audio(path):
    subprocess.run([bridge.utils.get_ffmpeg_binary(),'-nostdin','-v','error','-f','lavfi',
        '-i','sine=frequency=440:duration=2','-y',str(path)],check=True,capture_output=True)


def test_defaults_are_editorial_and_no_flow_or_credential_fields():
    assert Request(title='History').production.mode=='editorial'
    for kwargs in ({'video_source':'google_flow'},{'api_key':'secret'},{'image_limit':121}):
        with pytest.raises(ValidationError):VideoProduction(**kwargs)
    with pytest.raises(ValidationError):Request(title='History',publish_mode='public')


def test_voice_model_and_channel_settings_are_frozen(setup,monkeypatch):
    repo,snapshot,task_id,options=job(setup,monkeypatch)
    options.voice_name='pt-BR-AntonioNeural-Male'
    params=bridge.parameters(snapshot,{'title':'Approved title','script':'Approved script'},options)
    assert params.video_script=='Approved script' and params.video_aspect=='16:9'
    assert params.deepinfra_model=='PrunaAI/p-image' and not params.mixed_use_google_flow
    assert not params.mixed_use_grok and not params.mixed_use_flow and params.skill_snapshot==snapshot.skills
    original=dict(config.app)
    with bridge.runtime(snapshot,params,options):
        assert config.app['llm_provider']==snapshot.script_provider
        assert config.app['subtitle_provider']=='edge'
        assert not config.app['historical_archive_enabled']
        assert config.ui['mixed_use_deepinfra'] and not config.ui['mixed_use_google_flow']
    assert dict(config.app)==original


def test_real_audio_and_reopen_journal_do_not_repeat_tts(setup,monkeypatch):
    repo,snapshot,task_id,options=job(setup,monkeypatch,'narration')
    def tts(**kwargs):make_audio(Path(kwargs['voice_file']));return object()
    synth=Mock(side_effect=tts);monkeypatch.setattr(voice,'tts',synth)
    publish=Mock();monkeypatch.setattr(task,'_queue_cross_post',publish,raising=False)
    result={'title':'Historical title','script':'The independently approved narration.'}
    first=bridge.run(task_id,repo,snapshot,result,options)
    second=bridge.run(task_id,Repository(repo.path),snapshot,result,options)
    assert first==second and first['narration']['duration']>0
    assert synth.call_count==1 and not first['video_generated']
    saved=json.loads((bridge.directory(task_id)/'script.json').read_text())
    assert saved['script']==result['script'] and saved['params']['voice_name']==options.voice_name
    publish.assert_not_called()
    (bridge.directory(task_id)/'audio.mp3').write_bytes(b'changed')
    with pytest.raises(RecoveryBlocked,match='mudou'):bridge.run(task_id,repo,snapshot,result,options)
    assert synth.call_count==1


def test_interrupted_remote_narration_is_never_automatically_resubmitted(setup,monkeypatch):
    repo,snapshot,task_id,options=job(setup,monkeypatch,'narration')
    assert repo.begin_stage(task_id,'director_narration',remote=True) is None
    synth=Mock();monkeypatch.setattr(voice,'tts',synth)
    with pytest.raises(RecoveryBlocked,match='remota'):
        bridge.run(task_id,Repository(repo.path),snapshot,{'title':'Title','script':'Approved'},options)
    synth.assert_not_called()


def test_failed_media_reuses_audio_after_explicit_retry(setup,monkeypatch):
    repo,snapshot,task_id,options=job(setup,monkeypatch)
    monkeypatch.setattr(bridge,'preflight',lambda *args:None)
    def narrate(task_id,params):
        (bridge.directory(task_id)/'audio.mp3').write_bytes(b'validated audio')
        return {'files':[bridge.receipt(bridge.directory(task_id),'audio.mp3')],'duration':2}
    synth=Mock(side_effect=narrate);monkeypatch.setattr(bridge,'narrate',synth)
    def render(task_id,params):
        folder=bridge.directory(task_id);(folder/'final-1.mp4').write_bytes(b'validated video')
        return {**bridge.receipt(folder,'final-1.mp4'),'decode_verified':True,'published':False}
    assemble=Mock(side_effect=[RecoveryBlocked('Simulated interruption'),None]);monkeypatch.setattr(bridge,'assemble',assemble)
    result={'title':'Title','script':'Approved'}
    with pytest.raises(RecoveryBlocked):bridge.run(task_id,repo,snapshot,result,options)
    repo.finish_editorial(task_id,'blocked',error='Interrupted')
    repo.retry_editorial(task_id,acknowledge_cost=True)
    assemble.side_effect=render
    output=bridge.run(task_id,repo,snapshot,result,options)
    assert output['video_generated'] and not output['published'] and synth.call_count==1


def test_power_loss_after_final_render_uses_real_ffmpeg_validation(setup,monkeypatch):
    repo,snapshot,task_id,options=job(setup,monkeypatch)
    folder=bridge.directory(task_id)
    make_audio(folder/'audio.mp3')
    subprocess.run([bridge.utils.get_ffmpeg_binary(),'-nostdin','-v','error','-f','lavfi',
        '-i','color=c=blue:s=320x180:r=30:d=2','-f','lavfi','-i','sine=duration=2',
        '-c:v','libx264','-c:a','aac','-shortest','-y',str(folder/'final-1.mp4')],check=True,capture_output=True)
    (folder/'mixed-scenes.json').write_text(json.dumps({'scenes':[{'end_frame':60}]}))
    remote=Mock();monkeypatch.setattr(mixed_resume,'run',remote)
    final=bridge.assemble(task_id,bridge.parameters(snapshot,{'title':'Title','script':'Approved'},options))
    assert final['decode_verified'] and final['duration']==2 and not final['published']
    remote.assert_not_called()
    (folder/'final-1.mp4').write_bytes(b'broken partial mp4')
    with pytest.raises(Exception):bridge.assemble(task_id,None)
    remote.assert_not_called()


def test_preflight_failure_stops_before_new_narration(setup,monkeypatch):
    repo,snapshot,task_id,options=job(setup,monkeypatch)
    synth=Mock();monkeypatch.setattr(bridge,'narrate',synth)
    monkeypatch.setattr(bridge.utils,'check_ffmpeg_ready',lambda:False)
    with pytest.raises(RecoveryBlocked,match='FFmpeg'):
        bridge.run(task_id,repo,snapshot,{'title':'Title','script':'Approved'},options)
    synth.assert_not_called()


def test_real_existing_assembly_with_synthetic_provider_inputs(setup,monkeypatch):
    from app.models.schema import VideoAspect
    from app.services import mixed_materials
    repo,snapshot,task_id,options=job(setup,monkeypatch)
    monkeypatch.setattr(bridge,'preflight',lambda *args:None)
    monkeypatch.setattr(VideoAspect,'to_resolution',lambda self:(320,180))
    synth=Mock(side_effect=lambda **kw:(make_audio(Path(kw['voice_file'])) or object()))
    monkeypatch.setattr(voice,'tts',synth)
    def prepare(task_id,params,script,duration,subtitle):
        folder=bridge.directory(task_id)
        clip=folder/'scene.mp4'
        subprocess.run([bridge.utils.get_ffmpeg_binary(),'-nostdin','-v','error','-f','lavfi',
            '-i','color=c=blue:s=320x180:r=30:d='+str(duration),'-c:v','libx264',
            '-y',str(clip)],check=True,capture_output=True)
        (folder/'mixed-scenes.json').write_text(json.dumps({'scenes':[{'end_frame':round(duration*30)}]}))
        return [str(clip)]
    material=Mock(side_effect=prepare);monkeypatch.setattr(mixed_materials,'prepare',material)
    monkeypatch.setattr(mixed_materials,'image_requests',lambda task_id:0)
    no_publish=Mock(side_effect=AssertionError('Publication must never run'))
    monkeypatch.setattr(task,'_run_pipeline',no_publish)
    output=bridge.run(task_id,repo,snapshot,{'title':'Title','script':'Approved narration'},options)
    assert output['video_generated'] and output['video']['decode_verified']
    assert output['video']['width']==320 and output['video']['height']==180
    assert not output['video']['publish_allowed']
    assert synth.call_count==1 and material.call_count==1
    repeat=bridge.run(task_id,Repository(repo.path),snapshot,{'title':'Title','script':'Approved narration'},options)
    assert repeat==output and synth.call_count==1 and material.call_count==1
    no_publish.assert_not_called()


def test_legacy_editorial_batch_identity_survives_new_default_options(setup):
    import hashlib
    repo,snapshot=setup
    request=Request(title='Legacy documentary')
    old_request=request.model_dump(exclude={'production'})
    old_snapshot=snapshot.model_dump()
    old_snapshot['channel'].pop('research_backend',None)
    expected=hashlib.sha256(json.dumps({'request':old_request,'snapshot':old_snapshot},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    batch,created=repo.create_director_batch(request,snapshot)
    assert created and repo.director_batch(batch)['reference_id']==expected
    assert repo.create_director_batch(request,snapshot)==(batch,False)
    request.production=VideoProduction(mode='video')
    assert repo.create_director_batch(request,snapshot)[1]
