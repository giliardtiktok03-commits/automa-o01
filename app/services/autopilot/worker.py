"""One durable recovery worker, reusing mixed_resume and never cross-posting."""
import hashlib
import math
import subprocess
import threading

from filelock import FileLock, Timeout
from loguru import logger

from app.models.autopilot import ChannelProfile
from app.services.autopilot.repository import Repository
from app.services.autopilot import recovery
from app.services.historical_director.repository import DirectorPaused, DirectorCancelled
from app.utils import utils

_thread = None
_thread_guard = threading.Lock()
_stop = threading.Event()


def verify_final(folder):
    """Decode a final render before announcing recovery complete. Not publishing QA."""
    final = folder / "final-1.mp4"
    if final.is_symlink() or not final.is_file() or not final.stat().st_size:
        raise recovery.RecoveryBlocked("Saída final ausente ou vazia")
    try:
        from moviepy import VideoFileClip
        with VideoFileClip(str(final), audio=False) as clip:
            duration = float(clip.duration)
        manifest = recovery.read_json(folder / "mixed-scenes.json")
        expected = float(manifest["scenes"][-1]["end_frame"]) / 30
        if not math.isfinite(duration) or duration <= 0 or abs(duration - expected) > 1:
            raise ValueError()
    except (ValueError, KeyError, IndexError, OSError):
        raise recovery.RecoveryBlocked("Duração da saída final difere do plano de cenas") from None
    # xerror turns decoding errors into a nonzero exit. Never return stderr/URLs.
    try:
        result = subprocess.run([utils.get_ffmpeg_binary(), "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-i", str(final), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                                capture_output=True, timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise recovery.RecoveryBlocked("Não foi possível validar a saída final; confira o FFmpeg") from None
    if result.returncode:
        raise recovery.RecoveryBlocked("A saída final está incompleta, sem áudio/vídeo ou não pôde ser decodificada")
    checksum = hashlib.sha256()
    with final.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return {"file": final.name, "bytes": final.stat().st_size, "sha256": checksum.hexdigest(),
            "duration": duration, "decode_verified": True, "published": False}


def execute(job):
    from app.services import mixed_resume, webui_task, channel_skill_runtime, generation_progress
    from app.models import const
    from app.services import state as sm

    profile = ChannelProfile.model_validate_json(job["profile"])
    task_id = job["task_id"]
    folder = recovery.project_dir(task_id)
    project = recovery.inspect(task_id, verify_media=True)
    if project["editorial_digest"] != job["editorial_digest"]:
        raise recovery.RecoveryBlocked("Roteiro, voz ou áudio mudou após o vínculo; revise o projeto")
    if webui_task.is_generation_active(task_id):
        raise Timeout("Projeto ativo na interface")
    # A process can die after the render is saved but before the SQLite commit.
    with FileLock(str(folder / "mixed-resume.lock"), timeout=0):
        if (folder / "final-1.mp4").exists() or (folder / "final-1.mp4").is_symlink():
            return verify_final(folder)
    params = project["params"]
    if webui_task.is_generation_active(task_id):
        raise Timeout("Projeto ativo na interface")
    # Paid requests are controlled by the existing ledgers. No saved narration,
    # script, subtitle style or skill snapshot is replaced by the channel profile.
    snapshot = webui_task.capture_settings()
    snapshot.setdefault("ui", {})
    for source in ("pexels", "pixabay", "coverr", "deepinfra", "grok", "ai33"):
        snapshot["ui"]["mixed_use_" + source] = getattr(params, "mixed_use_" + source)
    if params.video_source == "deepinfra_image":
        snapshot["ui"]["mixed_use_deepinfra"] = True
    snapshot["ui"]["mixed_use_google_flow"] = False
    snapshot["ui"]["image_source_policy"] = "grok-v1"
    # One existing runtime lock also serializes manual WebUI generation.
    with webui_task._queued_settings(snapshot):
        with FileLock(str(folder / "mixed-resume.lock"), timeout=0):
            if (folder / "final-1.mp4").exists():
                return verify_final(folder)
        # Preserve the saved context in this new worker thread.
        with generation_progress.task_scope(task_id), channel_skill_runtime.scope(params.skill_snapshot):
            result = mixed_resume.run(task_id, profile.image_limit,
                                      grok_unlimited=params.mixed_grok_unlimited,
                                      deepinfra_unlimited=profile.deepinfra_unlimited)
    if not isinstance(result, dict) or not result.get("videos"):
        state = sm.state.get_task(task_id) or {}
        if state.get("state") == const.TASK_STATE_WAITING or (isinstance(result, dict) and result.get("state") == const.TASK_STATE_WAITING):
            return {"waiting_remote": True}
        raise recovery.RecoveryBlocked("Retomada interrompida. Confira o diagnóstico do projeto antes de tentar novamente")
    return verify_final(folder)


def run_once(repository=None, handler=None):
    repository = repository or Repository()
    if not repository.enabled():
        return False
    try:
        # OS-owned lock survives page reruns, coordinates multiple processes and
        # is released on process death. A stale lock file is harmless.
        with FileLock(str(repository.path) + ".worker.lock", timeout=0):
            job = repository.take() or repository.take_editorial()
            if job is None:
                return False
            editorial_job = job.get('kind') == 'editorial'
            finish = repository.finish_editorial if editorial_job else repository.finish
            try:
                if handler is not None:
                    result = handler(job)
                elif editorial_job:
                    from app.services.autopilot import editorial
                    item = repository.director_item(job['task_id'])
                    if item:
                        from app.services.historical_director import runner
                        result = runner.run(job, repository, item)
                    else:
                        result = editorial.run(job, repository)
                else:
                    result = execute(job)
            except DirectorPaused:
                finish(job["task_id"], "paused", error="Pausado entre etapas; resultados concluídos preservados")
            except DirectorCancelled:
                finish(job["task_id"], "cancelled", error="Cancelado em ponto seguro; uma chamada já aceita pode ter sido cobrada")
            except Timeout:
                finish(job["task_id"], "blocked" if editorial_job else "waiting_remote", error="Etapa ocupada; revise antes de repetir" if editorial_job else "Projeto ocupado; nova verificação automática em breve")
            except recovery.RecoveryBlocked as exc:
                finish(job["task_id"], "blocked", error=str(exc))
            except Exception:
                # Provider exceptions can carry keys/URLs. Never persist them.
                logger.warning("AUTOPILOT job stopped: task_id={}", job["task_id"])
                finish(job["task_id"], "failed", error="Falha na etapa editorial; confira o provedor antes de repetir" if editorial_job else "Falha na recuperação; materiais preservados. Confira o projeto")
            else:
                if result.get("waiting_remote"):
                    finish(job["task_id"], "waiting_remote")
                else:
                    finish(job["task_id"], "completed", result=result)
            return True
    except Timeout:
        return False


def loop(repository=None):
    repository = repository or Repository()
    while not _stop.is_set():
        try:
            run_once(repository)
        except Exception:
            logger.warning("AUTOPILOT journal unavailable; recovery will retry without submitting work")
        _stop.wait(2)


def ensure_started():
    global _thread
    with _thread_guard:
        if _thread is None or not _thread.is_alive():
            _stop.clear()
            _thread = threading.Thread(target=loop, name="mpt-autopilot", daemon=True)
            _thread.start()
