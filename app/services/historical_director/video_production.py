"""Bridge reviewed documentary packages to existing TTS and mixed video recovery.

Secrets remain in runtime config. The editorial job UUID owns all media files;
media recovery never submits a new narration or invokes any publisher.
"""
from contextlib import contextmanager
import hashlib
import math
from pathlib import Path
from uuid import UUID

from app.models.schema import VideoParams
from app.services.autopilot import editorial as ed
from app.services.autopilot.recovery import RecoveryBlocked
from app.services.autopilot.worker import verify_final
from app.services import channel_skill_runtime, generation_progress, webui_task
from app.utils import utils


def directory(task_id):
    task_id = str(UUID(str(task_id)))
    root = Path(utils.task_dir()).resolve()
    folder = root / task_id
    if folder.is_symlink() or not folder.resolve().is_relative_to(root):
        raise RecoveryBlocked('Pasta de produção inválida')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def receipt(folder, name):
    file = folder / name
    if Path(name).name != name or file.is_symlink() or not file.is_file() or not file.stat().st_size:
        raise RecoveryBlocked('Arquivo de produção ausente ou inválido: ' + name)
    digest = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'file': name, 'sha256': digest.hexdigest(), 'bytes': file.stat().st_size}


def verify_receipts(folder, saved):
    for expected in saved['files']:
        if receipt(folder, expected['file']) != expected:
            raise RecoveryBlocked('Narração ou legenda mudou; restaure o arquivo original antes de retomar')


def parameters(snapshot, result, options):
    return VideoParams(video_subject=result['title'], video_script=result['script'],
        video_language=snapshot.channel.language, skills_enabled=True,
        skill_ids=[s.skill_id for s in snapshot.skills], skill_snapshot=snapshot.skills,
        voice_name=options.voice_name, voice_rate=options.voice_rate,
        subtitle_enabled=options.subtitle_enabled, font_name=options.font_name,
        video_source=options.video_source, video_aspect='16:9', video_concat_mode='sequential',
        video_count=1, match_materials_to_script=True, mixed_select_sources=True,
        mixed_use_pexels=options.use_pexels and options.video_source=='mixed',
        mixed_use_pixabay=options.use_pixabay and options.video_source=='mixed',
        mixed_use_coverr=False, mixed_use_deepinfra=True, mixed_image_provider='deepinfra',
        deepinfra_model=options.deepinfra_model, mixed_max_images=options.image_limit,
        mixed_deepinfra_unlimited=options.deepinfra_unlimited, mixed_grok_unlimited=False,
        mixed_use_grok=False, mixed_use_ai33=False, mixed_use_google_flow=False,
        mixed_use_flow=False, mixed_use_openai=False, mixed_use_runware=False,
        mixed_visual_validation=options.visual_validation,
        bgm_type='random' if options.music_enabled else '',
        bgm_volume=options.music_volume if options.music_enabled else 0)


@contextmanager
def runtime(snapshot, params, options):
    # Same lock as manual WebUI jobs. It also restores settings on failure.
    settings = webui_task.capture_settings()
    settings['app'] = ed.settings_for(snapshot)
    settings['app']['subtitle_provider'] = options.subtitle_provider
    settings['app']['historical_archive_enabled'] = False
    settings.setdefault('ui', {})
    for source in ('pexels','pixabay','coverr','deepinfra','grok','ai33','google_flow'):
        settings['ui']['mixed_use_'+source] = getattr(params,'mixed_use_'+source)
    settings['ui']['image_source_policy'] = 'grok-v1'
    with webui_task._queued_settings(settings), channel_skill_runtime.scope(params.skill_snapshot):
        yield


def preflight(params, options):
    if not utils.check_ffmpeg_ready():
        raise RecoveryBlocked('FFmpeg indisponível; configure antes de produzir a narração')
    if options.mode == 'video':
        from app.services import mixed_materials, video, bgm_service
        try:
            mixed_materials.validate(params)
        except mixed_materials.MixedError:
            raise RecoveryBlocked('Configuração de mídia indisponível. Confira a chave DeepInfra, as fontes selecionadas e o acesso OpenAI para validação visual antes de iniciar') from None
        if params.subtitle_enabled:
            if not Path(utils.font_dir(params.font_name)).is_file():
                raise RecoveryBlocked('Fonte de legenda não encontrada; selecione uma fonte instalada no MPT')
            video.validate_subtitle_colors(params)
        if options.music_enabled and not bgm_service.list_bgm_files():
            raise RecoveryBlocked('Música ativada, mas a biblioteca local está vazia; adicione música ou desative a opção')


def narrate(task_id, params):
    from app.services import task, voice
    # Existing TTS adapter, including all provider dispatch and subtitle timing.
    task.save_script_data(task_id, params.video_script, '', params)
    audio, duration, timing = task.generate_audio(task_id, params, params.video_script)
    if not audio or not math.isfinite(duration) or duration <= 0:
        raise RecoveryBlocked('Falha na narração; confira a voz e o provedor no MPT antes de autorizar nova tentativa')
    folder = directory(task_id)
    if Path(audio).resolve() != (folder/'audio.mp3').resolve():
        raise RecoveryBlocked('Narração fora da pasta da tarefa')
    files = [receipt(folder, 'audio.mp3')]
    actual_duration = voice.get_audio_duration(audio)
    if not math.isfinite(actual_duration) or actual_duration <= 0:
        raise RecoveryBlocked('Narração vazia ou sem duração válida')
    if params.subtitle_enabled:
        subtitle = task.generate_subtitle(task_id, params, params.video_script, timing, audio)
        if not subtitle or Path(subtitle).resolve() != (folder/'subtitle.srt').resolve():
            raise RecoveryBlocked('O provedor não produziu legendas temporizadas; revise as configurações antes de repetir')
        files.append(receipt(folder, 'subtitle.srt'))
    return {'files': files, 'duration': actual_duration, 'published': False}


def verify_video(folder):
    final = verify_final(folder)
    from moviepy import VideoFileClip
    from app.services import voice
    with VideoFileClip(str(folder/final['file'])) as clip:
        width, height = clip.size
        if abs(width / height - 16 / 9) > 0.01 or clip.audio is None:
            raise RecoveryBlocked('Vídeo final precisa ter imagem 16:9 e áudio')
        audio_duration = float(clip.audio.duration)
    narration_duration = voice.get_audio_duration(str(folder/'audio.mp3'))
    if (not math.isfinite(narration_duration) or narration_duration <= 0
            or abs(audio_duration - narration_duration) > 1
            or abs(final['duration'] - narration_duration) > 1):
        raise RecoveryBlocked('Duração do vídeo ou áudio final difere da narração')
    return {**final, 'width':width, 'height':height, 'narration_duration':narration_duration,
            'scope':'technical_render', 'publish_allowed':False}


def assemble(task_id, params):
    from app.services import mixed_resume
    folder = directory(task_id)
    # Recover a render saved just before a crash without generating anything.
    if (folder/'final-1.mp4').exists() or (folder/'final-1.mp4').is_symlink():
        return verify_video(folder)
    result = mixed_resume.run(task_id, params.mixed_max_images,
        grok_unlimited=False, deepinfra_unlimited=params.mixed_deepinfra_unlimited)
    if not isinstance(result, dict) or not result.get('videos'):
        raise RecoveryBlocked('Produção de vídeo interrompida. Materiais preservados; confira o diagnóstico em storage/tasks/'+task_id+' antes de retomar')
    return verify_video(folder)


def run(task_id, repo, snapshot, result, options):
    params = parameters(snapshot, result, options)
    folder = directory(task_id)
    with runtime(snapshot, params, options), generation_progress.task_scope(task_id):
        # Local preflight runs before any new TTS request, even on cached stages.
        preflight(params, options)
        audio = ed.step(repo, task_id, 'director_narration', lambda:narrate(task_id, params))
        verify_receipts(folder, audio)
        output = {'mode':options.mode, 'narration':audio, 'published':False, 'video_generated':False}
        if options.mode == 'video':
            final = ed.step(repo, task_id, 'director_video', lambda:assemble(task_id, params), remote=False)
            if receipt(folder, final['file']) != {k:final[k] for k in ('file','sha256','bytes')}:
                raise RecoveryBlocked('Vídeo final alterado; restaure a saída original')
            output.update(video=final,video_generated=True)
        return output
