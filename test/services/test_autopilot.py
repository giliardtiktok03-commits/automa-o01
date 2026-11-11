import json
from pathlib import Path
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.autopilot import ChannelProfile
from app.models.schema import VideoParams
from app.services.autopilot.repository import Repository, Conflict
from app.services.autopilot import recovery, worker

DIGEST = 'a' * 64


@pytest.fixture
def repo(tmp_path):
    db = Repository(tmp_path / 'autopilot.sqlite3')
    db.save_channel(ChannelProfile(channel_id='history', name='História', auto_resume=True, deepinfra_unlimited=True))
    db.set_enabled(True)
    return db


@pytest.fixture
def project(tmp_path, monkeypatch):
    from app.services import mixed_resume
    root = tmp_path / 'tasks'
    root.mkdir()
    task_id = str(uuid4())
    folder = root / task_id
    folder.mkdir()
    params = VideoParams(video_subject='Título original', video_source='mixed', mixed_use_deepinfra=True,
                         subtitle_enabled=False, voice_name='approved-voice')
    (folder/'audio.mp3').write_bytes(b'original audio')
    (folder/'script.json').write_text(json.dumps({'script': 'Original narration.', 'params': params.model_dump(mode='json')}))
    (folder/'mixed-scenes.json').write_text(json.dumps({'image_requests': 100, 'scenes': [
        {'id': 1, 'end_frame': 90, 'sha256': 'ready', 'provenance': {'provider': 'deepinfra_image'}},
        {'id': 2, 'end_frame': 180}]}))
    def task_dir(task=''):
        target = root / task
        target.mkdir(exist_ok=True)
        return str(target)
    monkeypatch.setattr(recovery.utils, 'task_dir', task_dir)
    return task_id, folder


def enroll(repo, project):
    task_id, _ = project
    item = recovery.inspect(task_id, verify_media=True)
    repo.enroll(task_id, 'history', item['title'], item['editorial_digest'])
    return repo.get(task_id)


def test_snapshot_versions_duplicate_click_and_channel_isolation(repo):
    task_id = str(uuid4())
    assert repo.enroll(task_id, 'history', 'Title', DIGEST)
    assert not repo.enroll(task_id, 'history', 'Other', DIGEST)
    assert len(repo.jobs()) == 1
    repo.save_channel(ChannelProfile(channel_id='other', name='Cozinha'))
    with pytest.raises(Conflict):
        repo.enroll(task_id, 'other', 'Title', DIGEST)
    original = repo.get(task_id)['profile']
    repo.save_channel(ChannelProfile(channel_id='history', name='Changed', auto_resume=True), expected_version=1)
    assert repo.get(task_id)['profile'] == original
    assert repo.get(task_id)['channel_version'] == 1
    with pytest.raises(Conflict):
        repo.save_channel(ChannelProfile(channel_id='history', name='Stale'), expected_version=1)


def test_model_rejects_credentials_and_unsafe_inputs():
    with pytest.raises(ValidationError):
        ChannelProfile(channel_id='x', name='X', api_key='private')
    for value in ['../escape', 'with spaces', 'CAPS', '']:
        with pytest.raises(ValidationError):
            ChannelProfile(channel_id=value, name='X')


def test_discovery_reads_metadata_without_hashing_videos_or_network(project):
    task_id, folder = project
    (folder/'mixed').mkdir()
    (folder/'mixed/vid-large.mp4').write_bytes(b'preserve this')
    found = recovery.discover()
    assert len(found) == 1 and found[0]['task_id'] == task_id
    assert found[0]['registered'] == 1 and found[0]['total'] == 2
    assert 'params' not in found[0]
    assert (folder/'mixed/vid-large.mp4').read_bytes() == b'preserve this'


def test_discovery_excludes_flow_and_chapter_projects(project):
    task_id, folder = project
    source = json.loads((folder/'script.json').read_text())
    for key, value in [('long_form', True), ('video_source', 'google_flow')]:
        saved = json.loads(json.dumps(source))
        saved['params'][key] = value
        (folder/'script.json').write_text(json.dumps(saved))
        assert recovery.discover() == []


def test_symlink_and_broken_manifests_never_escape_project(project, tmp_path):
    task_id, folder = project
    (folder/'mixed').symlink_to(tmp_path, target_is_directory=True)
    assert recovery.discover() == []
    (folder/'mixed').unlink()
    (folder/'mixed-scenes.json').write_text('{broken')
    assert recovery.discover() == []
    with pytest.raises(ValueError):
        recovery.project_dir('../escape')


def test_two_workers_cannot_execute_same_job(repo):
    task_id = str(uuid4())
    repo.enroll(task_id, 'history', 'Title', DIGEST)
    entered = threading.Event()
    release = threading.Event()
    def handler(job):
        entered.set()
        assert release.wait(5)
        return {'file': 'final-1.mp4', 'published': False}
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(worker.run_once, repo, handler)
        assert entered.wait(5)
        assert worker.run_once(Repository(repo.path), handler) is False
        release.set()
        assert first.result()
    assert repo.get(task_id)['state'] == 'completed'
    assert not worker.run_once(repo, handler)


def test_disabled_worker_and_channel_do_not_run_jobs(repo):
    task_id = str(uuid4())
    repo.enroll(task_id, 'history', 'Title', DIGEST)
    handler = Mock()
    repo.set_enabled(False)
    assert not worker.run_once(repo, handler)
    repo.set_enabled(True)
    repo.save_channel(ChannelProfile(channel_id='history', name='Paused', auto_resume=False), expected_version=1)
    assert not worker.run_once(repo, handler)
    handler.assert_not_called()
    assert repo.get(task_id)['state'] == 'queued'


def test_restart_recovers_running_job_without_entering_id_again(repo):
    task_id = str(uuid4())
    repo.enroll(task_id, 'history', 'Title', DIGEST)
    # A real process terminates with a durable running record and OS lock held.
    code = '''
import os,sys
from app.services.autopilot.repository import Repository
from app.services.autopilot.worker import run_once
def crash(job): os._exit(23)
run_once(Repository(sys.argv[1]), crash)
'''
    result = subprocess.run([sys.executable, '-c', code, str(repo.path)], cwd=Path(__file__).parents[2], timeout=30)
    assert result.returncode == 23
    assert Repository(repo.path).get(task_id)['state'] == 'running'
    handler = Mock(return_value={'published': False})
    assert worker.run_once(Repository(repo.path), handler)
    assert handler.call_args.args[0]['task_id'] == task_id
    assert repo.get(task_id)['state'] == 'completed'


def test_remote_pending_is_delayed_and_resumed_without_duplicate_job(repo, monkeypatch):
    task_id = str(uuid4())
    repo.enroll(task_id, 'history', 'Title', DIGEST)
    handler = Mock(return_value={'waiting_remote': True})
    worker.run_once(repo, handler)
    assert repo.get(task_id)['state'] == 'waiting_remote'
    assert not worker.run_once(repo, handler)
    with repo.connect() as db:
        db.execute('UPDATE jobs SET next_attempt=0')
    handler.return_value = {'published': False}
    assert worker.run_once(repo, handler)
    assert repo.get(task_id)['state'] == 'completed'
    assert len(repo.jobs()) == 1


def test_provider_errors_are_not_persisted_or_automatically_retried(repo):
    task_id = str(uuid4())
    repo.enroll(task_id, 'history', 'Title', DIGEST)
    handler = Mock(side_effect=RuntimeError('secret-key signed-url'))
    worker.run_once(repo, handler)
    assert repo.get(task_id)['state'] == 'failed'
    assert 'secret-key' not in repo.get(task_id)['error']
    assert not worker.run_once(repo, handler)
    assert repo.retry(task_id)
    assert repo.get(task_id)['state'] == 'queued'


def test_recovery_preserves_editorial_and_restores_live_settings(repo, project, monkeypatch):
    from app.services import mixed_resume, webui_task, channel_skill_runtime
    from app.config import config
    job = enroll(repo, project)
    original = dict(config.ui)
    def resume(task_id, limit, **kwargs):
        assert kwargs['deepinfra_unlimited'] is True
        assert config.ui['mixed_use_deepinfra'] is True
        assert config.ui['mixed_use_google_flow'] is False
        assert 'subtitle_settings' not in kwargs
        return {'videos': ['final-1.mp4']}
    request = Mock(side_effect=resume)
    monkeypatch.setattr(mixed_resume, 'run', request)
    monkeypatch.setattr(worker, 'verify_final', lambda folder: {'published': False})
    monkeypatch.setattr(webui_task, 'is_generation_active', lambda _: False)
    assert worker.execute(job)['published'] is False
    assert config.ui == original
    request.assert_called_once()
    assert json.loads((project[1]/'script.json').read_text())['params']['voice_name'] == 'approved-voice'


def test_changed_editorial_blocks_before_any_paid_work(repo, project, monkeypatch):
    from app.services import mixed_resume
    job = enroll(repo, project)
    saved = json.loads((project[1]/'script.json').read_text())
    saved['script'] = 'Changed after enrollment'
    (project[1]/'script.json').write_text(json.dumps(saved))
    paid = Mock()
    monkeypatch.setattr(mixed_resume, 'run', paid)
    with pytest.raises(recovery.RecoveryBlocked, match='mudou'):
        worker.execute(job)
    paid.assert_not_called()


def test_unknown_image_result_remains_blocked_without_resubmission(repo, project, monkeypatch):
    from app.services import mixed_resume
    job = enroll(repo, project)
    paid = Mock(side_effect=ValueError('unknown paid result'))
    monkeypatch.setattr(mixed_resume, 'run', paid)
    worker.run_once(repo)
    assert repo.get(job['task_id'])['state'] == 'failed'
    assert not worker.run_once(repo)
    paid.assert_called_once()


def test_changed_audio_blocks_recovery_before_paid_work(repo, project, monkeypatch):
    from app.services import mixed_resume
    job = enroll(repo, project)
    (project[1]/'audio.mp3').write_bytes(b'changed audio')
    paid = Mock()
    monkeypatch.setattr(mixed_resume, 'run', paid)
    with pytest.raises(recovery.RecoveryBlocked, match='mudou'):
        worker.execute(job)
    paid.assert_not_called()


def test_explicit_retry_can_adopt_new_channel_budget_without_touching_project(repo):
    task_id = str(uuid4())
    repo.enroll(task_id, 'history', 'Title', DIGEST)
    worker.run_once(repo, Mock(side_effect=recovery.RecoveryBlocked('review')))
    repo.save_channel(ChannelProfile(channel_id='history', name='History', auto_resume=True, deepinfra_unlimited=False), expected_version=1)
    assert repo.retry(task_id, refresh_profile=True)
    assert repo.get(task_id)['channel_version'] == 2
    assert json.loads(repo.get(task_id)['profile'])['deepinfra_unlimited'] is False


def test_native_final_decode_and_duration_are_verified(tmp_path):
    folder = tmp_path / 'project'
    folder.mkdir()
    manifest = {'scenes': [{'end_frame': 6}]}
    (folder/'mixed-scenes.json').write_text(json.dumps(manifest))
    final = folder/'final-1.mp4'
    binary = worker.utils.get_ffmpeg_binary()
    subprocess.run([binary, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=30',
                    '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
                    '-t', '0.2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(final)], check=True, timeout=30)
    result = worker.verify_final(folder)
    assert result['decode_verified'] and result['published'] is False
    assert len(result['sha256']) == 64
    manifest['scenes'][0]['end_frame'] = 900
    (folder/'mixed-scenes.json').write_text(json.dumps(manifest))
    with pytest.raises(recovery.RecoveryBlocked, match='Duração'):
        worker.verify_final(folder)
    final.write_bytes(b'broken final')
    with pytest.raises((recovery.RecoveryBlocked, OSError)):
        worker.verify_final(folder)


def test_existing_complete_render_does_not_submit_resume_again(repo, project, monkeypatch):
    from app.services import mixed_resume
    job = enroll(repo, project)
    (project[1]/'final-1.mp4').write_bytes(b'already saved')
    paid = Mock()
    monkeypatch.setattr(mixed_resume, 'run', paid)
    monkeypatch.setattr(worker, 'verify_final', lambda _: {'decode_verified': True, 'published': False})
    assert worker.execute(job)['decode_verified']
    paid.assert_not_called()


def test_partial_render_is_blocked_without_deleting_source(repo, project, monkeypatch):
    job = enroll(repo, project)
    final = project[1]/'final-1.mp4'
    final.write_bytes(b'partial')
    monkeypatch.setattr(worker, 'verify_final', Mock(side_effect=recovery.RecoveryBlocked('Saída incompleta')))
    worker.run_once(repo)
    assert repo.get(job['task_id'])['state'] == 'blocked'
    assert final.read_bytes() == b'partial'


def test_real_resume_entry_does_not_publish_or_regenerate_narration(repo, project, monkeypatch):
    from app.services import mixed_resume, task, upload_post
    job = enroll(repo, project)
    monkeypatch.setattr(mixed_resume.voice, 'get_audio_duration', lambda _: 6)
    monkeypatch.setattr(mixed_resume.mixed_materials, 'prepare', lambda *a: ['scene.mp4'])
    def render(*args):
        out = project[1]/'final-1.mp4'
        out.write_bytes(b'rendered')
        return [str(out)], [], []
    monkeypatch.setattr(task, 'generate_final_videos', render)
    monkeypatch.setattr(worker, 'verify_final', lambda _: {'decode_verified': True, 'published': False})
    publish = Mock(side_effect=AssertionError('Must never publish during recovery'))
    narration = Mock(side_effect=AssertionError('Must reuse saved narration'))
    monkeypatch.setattr(task, '_schedule_cross_post', publish)
    monkeypatch.setattr(upload_post, 'cross_post_video', publish)
    monkeypatch.setattr(task, 'generate_audio', narration)
    assert worker.execute(job)['published'] is False
    publish.assert_not_called()
    narration.assert_not_called()
    assert json.loads((project[1]/'mixed-scenes.json').read_text())['image_requests'] == 100
