"""Resume a saved single-video mixed project without regenerating narration."""

import json
import math
from pathlib import Path, PureWindowsPath
import re
import shutil
from datetime import datetime, timezone
from uuid import UUID

from filelock import FileLock
from app.models.schema import VideoParams
from app.models import const
from app.services import mixed_materials, task_artifacts, generation_progress, voice
from app.services import state as sm
from app.utils import utils


def _local(directory, name):
    candidate = (directory / name).resolve()
    if not candidate.is_relative_to(directory.resolve()) or not candidate.is_file():
        raise ValueError(f"Project file missing or outside project: {name}")
    return candidate


def load(task_id, limit, *, grok_unlimited=None, deepinfra_unlimited=None):
    task_id = str(UUID(task_id.strip()))
    directory = Path(utils.task_dir(task_id))
    if not directory.resolve().is_relative_to(Path(utils.task_dir()).resolve()):
        raise ValueError("Project directory is outside storage/tasks")
    if (directory / "final-1.mp4").is_file() and (
        directory / "final-1.mp4"
    ).stat().st_size:
        raise ValueError(
            "This project already has a final video; open its result instead of resuming"
        )
    script_file = _local(directory, "script.json")
    manifest_file = directory / "mixed-scenes.json"
    missing_plan = not manifest_file.exists()
    if manifest_file.is_symlink():
        raise ValueError("Invalid scene checkpoint path")
    if missing_plan and (directory / "mixed").exists() and any((directory / "mixed").iterdir()):
        raise ValueError("Materiais existentes sem manifesto; revise antes de retomar para evitar solicitações duplicadas")
    saved = json.loads(script_file.read_text(encoding="utf-8"))
    manifest = {"image_requests": 0, "scenes": []} if missing_plan else json.loads(_local(directory,"mixed-scenes.json").read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if not missing_plan and (
        not scenes
        or len(scenes) > mixed_materials.MAX_SHOTS
        or [s.get("id") for s in scenes] != list(range(1, len(scenes) + 1))
    ):
        raise ValueError("Invalid scene checkpoint")
    params = VideoParams.model_validate(saved["params"])
    if params.video_source not in {"mixed", "google_flow", "ai33_image", "grok_image", "runware_image", "deepinfra_image"} or params.long_form or params.mixed_is_chapter:
        raise ValueError(
            "This resume action requires a single-video mixed project; use chapter resume for long-form projects"
        )
    params.mixed_resume = True
    params.mixed_max_images = VideoParams(
        video_subject="limit", mixed_max_images=limit
    ).mixed_max_images
    if grok_unlimited is not None:
        params.mixed_grok_unlimited = bool(grok_unlimited)
    if deepinfra_unlimited is not None:
        params.mixed_deepinfra_unlimited = bool(deepinfra_unlimited)
    from app.config import config
    uses_unlimited_deepinfra = params.mixed_deepinfra_unlimited and (params.video_source == "deepinfra_image" or (params.video_source == "mixed" and bool(config.ui.get("mixed_use_deepinfra", False))))
    uses_unlimited_grok = (params.mixed_grok_unlimited and params.video_source not in {"ai33_image", "deepinfra_image"} and not bool(config.ui.get("mixed_use_deepinfra", False))
                          and bool(config.ui.get("mixed_use_grok", True))) or params.video_source == "google_flow" or (bool(config.ui.get("mixed_use_google_flow", False)) and not bool(config.ui.get("mixed_use_deepinfra", False)) and params.video_source != "deepinfra_image")

    if not (uses_unlimited_grok or uses_unlimited_deepinfra) and limit < manifest["image_requests"]:
        raise ValueError("New total limit cannot be below requests already started")
    script = saved.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ValueError("Saved script is missing")
    params.video_script = script
    audio_name = (
        PureWindowsPath(params.custom_audio_file).name
        if params.custom_audio_file
        else "audio.mp3"
    )
    audio = _local(directory, audio_name)
    digest = mixed_materials._hash(audio)
    expected = re.fullmatch(r"custom-audio-([0-9a-f]{64})\.[\w]+", audio_name)
    if expected and expected.group(1) != digest:
        raise ValueError("Uploaded audio changed; restore the original project file")
    subtitle = _local(directory, "subtitle.srt") if params.subtitle_enabled else None
    media = {
        "audio": digest,
        "subtitle": mixed_materials._hash(subtitle) if subtitle else None,
    }
    metadata_file = directory / "resume-media.json"
    if metadata_file.exists() and json.loads(metadata_file.read_text()) != media:
        raise ValueError("Audio or subtitle file changed since the previous resume")
    ready = 0
    for scene in manifest["scenes"]:
        rendered = directory / "mixed" / f"scene-{scene['id']:03d}.mp4"
        if rendered.is_file() and scene.get("sha256") == mixed_materials._hash(
            rendered
        ):
            ready += 1
            continue
        if scene.get("image_file"):
            image = _local(directory / "mixed", Path(scene["image_file"]).name)
            if mixed_materials._hash(image) != scene.get("image_sha256"):
                raise ValueError(
                    "A previously generated image changed; review project before resuming"
                )
        elif scene.get("image_request_started") and not scene.get("image_refused"):
            provider = "deepinfra" if scene.get("deepinfra_job") else "google_flow" if scene.get("google_flow_job") else "grok" if scene.get("grok_job") else "runware" if scene.get("runware_job") else "ai33"
            ledger = directory / "mixed" / f"{provider}-{scene['id']:03d}" / ("flow-image.json" if provider == "google_flow" else provider + "-image.json")
            if not scene.get(provider + "_job") or not ledger.is_file():
                raise ValueError("A previous image request has an unknown result; review it before resuming, no automatic resubmission")
            from app.services.ai33 import AI33Client
            attempt = json.loads(ledger.read_text(encoding="utf-8"))
            if not AI33Client.valid_task_id(attempt.get("task_id") or attempt.get("request_id")):
                raise ValueError("Image submission is unconfirmed; reconcile before resuming")
    duration = voice.get_audio_duration(str(audio))
    if not params.custom_audio_file:
        duration = math.ceil(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Saved audio duration is invalid")
    return dict(
        task_id=task_id,
        directory=directory,
        params=params,
        script=script,
        manifest=manifest,
        audio=str(audio),
        subtitle=str(subtitle) if subtitle else "",
        duration=duration,
        ready=ready,
        total=len(manifest["scenes"]),
        started=manifest["image_requests"],
        media=media,
        planning_required=missing_plan,
    )


def run(task_id, limit, *, grok_unlimited=None, deepinfra_unlimited=None, subtitle_settings=None):
    from app.services import task

    sm.state.update_task(task_id, error=None, error_key=None, error_params={}, failed_stage=None)
    project = load(task_id, limit, grok_unlimited=grok_unlimited, deepinfra_unlimited=deepinfra_unlimited)
    directory = project["directory"]
    with FileLock(str(directory / "mixed-resume.lock"), timeout=0):
        # Keep a pre-resume copy of manifests. Never move/delete source media.
        backup = (
            directory
            / "resume-backups"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
        backup.mkdir(parents=True)
        for name in ("script.json", "mixed-scenes.json"):
            if (directory / name).is_file():
                shutil.copy2(_local(directory, name), backup / name)
        task_artifacts._write_json_atomic(
            directory / "resume-media.json", project["media"]
        )
        params = project["params"]
        if subtitle_settings:
            from app.services import subtitle_style
            params = subtitle_style.apply(params, subtitle_settings)
            # Enabling subtitles requires an existing timeline; do not retranscribe.
            if params.subtitle_enabled and not project["subtitle"]:
                raise ValueError("O projeto não tem SRT salvo; desative legendas ou gere a transcrição antes de retomar")
        # Current source preferences affect only new images; paid jobs keep their provider.
        from app.config import config
        params.mixed_use_google_flow = params.video_source == "google_flow" or (bool(config.ui.get("mixed_use_google_flow", False)) and not bool(config.ui.get("mixed_use_deepinfra", False)) and params.video_source != "deepinfra_image")
        params.mixed_use_deepinfra = params.video_source == "deepinfra_image" or (params.video_source == "mixed" and bool(config.ui.get("mixed_use_deepinfra", False)))
        params.mixed_use_runware = False
        params.mixed_use_grok = bool(config.ui.get("mixed_use_grok", True))
        params.mixed_use_ai33 = bool(config.ui.get("mixed_use_ai33", False)) if config.ui.get("image_source_policy") == "grok-v1" else False
        if params.video_source == "deepinfra_image":
            params.mixed_use_google_flow = params.mixed_use_grok = params.mixed_use_ai33 = False
        elif params.video_source == "ai33_image":
            params.mixed_use_runware = False
            params.mixed_use_grok = False
            params.mixed_use_ai33 = True
        elif params.video_source in {"grok_image", "runware_image"}:
            params.mixed_use_grok = True
            params.mixed_use_ai33 = False
        sm.state.update_task(
            project["task_id"],
            state=const.TASK_STATE_PROCESSING,
            progress=40,
            error=None,
            failed_stage=None,
            video_subject=params.video_subject,
            resume_completed_scenes=project["ready"],
        )
        generation_progress.stage("materials")
        try:
            materials = mixed_materials.prepare(
                project["task_id"],
                params,
                project["script"],
                project["duration"],
                project["subtitle"],
            )
            generation_progress.stage("rendering")
            videos, combined, warnings = task.generate_final_videos(
                project["task_id"],
                params,
                materials,
                project["audio"],
                project["subtitle"],
                project["duration"],
            )
            if not videos:
                raise ValueError("Final render did not produce a video")
        except mixed_materials.MixedPending as pending:
            return task._mark_provider_pending(project["task_id"], pending)
        except Exception as exc:
            return task._mark_task_failed(project["task_id"], "resume", str(exc))
        task_artifacts.patch_script_data(
            project["task_id"], params=params.model_dump(mode="json")
        )
        result = dict(
            videos=videos,
            combined_videos=combined,
            warnings=warnings or None,
            audio_file=project["audio"],
            subtitle_path=project["subtitle"],
            mixed_image_requests=mixed_materials.image_requests(project["task_id"]),
        )
        sm.state.update_task(
            project["task_id"], state=const.TASK_STATE_COMPLETE, progress=100, **result
        )
        return dict(
            task_id=project["task_id"], state=const.TASK_STATE_COMPLETE, **result
        )
