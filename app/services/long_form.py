"""Sequential, checkpointed chapter generation using the normal video pipeline."""

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from filelock import FileLock, Timeout
from moviepy import VideoFileClip

from app.config import config
from app.models import const
from app.models.schema import VideoParams
from app.services import generation_progress, llm, narration, subtitle, task_artifacts, voice
from app.services import state as sm
from app.utils import utils


class ChapterError(RuntimeError):
    pass


def validate(params, *, external_audio=False):
    if params.video_source in {"mixed", "ai33_image", "grok_image", "runware_image"}:
        from app.services import mixed_materials

        mixed_materials.validate(params, external_audio=external_audio)
    if params.video_count != 1:
        raise ValueError("Chapter mode generates one final video; set video_count=1")
    has_audio = bool(params.custom_audio_file) or external_audio
    if not has_audio and not (params.voice_name or "").strip():
        raise ValueError("Chapter mode requires a TTS voice or uploaded narration")
    if params.video_source == "loomloom":
        raise ValueError("Chapter mode does not support LoomLoom batches")
    if not has_audio and (not params.voice_rate or not math.isfinite(params.voice_rate) or params.voice_rate <= 0):
        raise ValueError("Chapter mode requires a finite positive voice_rate")
    if has_audio:
        whisper = config.app.get("subtitle_provider", "edge") == "whisper"
        if not params.video_script.strip() and not whisper:
            raise ValueError("For uploaded chapter narration, supply the full transcript or select Whisper transcription")
        if params.subtitle_enabled and not whisper:
            raise ValueError("Select Whisper for subtitles from uploaded narration, or disable subtitles")
    if not utils.check_ffmpeg_ready():
        raise ValueError("Chapter mode requires a working FFmpeg installation")


def _save(file, value):
    """Never expose a partially written checkpoint after interruption."""
    fd, temporary = tempfile.mkstemp(dir=file.parent, prefix=".chapters-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _digest(file):
    checksum = hashlib.sha256()
    with open(file, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _fingerprint(params, references):
    payload = {"params": params.model_dump(mode="json"), "references": references}
    payload["params"].pop("mixed_resume", None)
    payload["params"].pop("mixed_resume_subtitle_style", None)
    if not params.subtitle_soft_shadow:
        payload["params"].pop("subtitle_soft_shadow", None)
    if not params.subtitle_max_lines:
        payload["params"].pop("subtitle_max_lines", None)
    payload["params"].pop("mixed_grok_unlimited", None)
    if params.mixed_image_provider != "grok":
        for key in ("grok_model", "mixed_use_grok"):
            payload["params"].pop(key, None)
    if params.mixed_image_provider != "runware":
        for key in ("runware_model", "runware_steps", "runware_size", "mixed_use_runware"):
            payload["params"].pop(key, None)
    if not params.skills_enabled or not params.skill_snapshot:
        for key in ("skills_enabled", "skill_ids", "skill_snapshot"):
            payload["params"].pop(key, None)
    if params.video_source not in {"mixed", "ai33_image", "grok_image", "runware_image"}:
        for key in ("mixed_max_images", "mixed_scene_duration", "mixed_visual_validation", "mixed_vision_model", "mixed_max_candidates", "mixed_variable_pacing", "mixed_timeline_offset", "mixed_total_duration", "mixed_previous_sources", "mixed_is_chapter", "mixed_image_provider", "flow_profile", "flow_project_url", "flow_require_zero", "mixed_select_sources", "mixed_use_pexels", "mixed_use_pixabay", "mixed_use_coverr", "mixed_use_openai", "mixed_use_flow", "mixed_use_ai33", "mixed_use_runware", "mixed_use_grok", "grok_model", "runware_model", "runware_steps", "runware_size", "ai33_model", "ai33_resolution", "ai33_quality", "ai33_max_credits"):
            payload["params"].pop(key, None)
    if params.custom_audio_file:
        # Re-uploading the same recording from another path must still resume.
        payload["params"]["custom_audio_file"] = "<external-narration>"
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _split_script(script, count):
    # Prefer sentence boundaries; never drop or duplicate user-supplied text.
    sentences = re.split(r"(?<=[.!?])\s+|(?<=[。！？])|\n\s*\n", script.strip())
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if len(sentences) < count:
        # Scripts without sentence punctuation still need bounded chapter inputs.
        sentences = script.split()
    count = min(count, len(sentences))
    groups, current, size = [], [], 0
    remaining_size = sum(len(sentence) for sentence in sentences)
    for index, sentence in enumerate(sentences):
        current.append(sentence)
        size += len(sentence)
        groups_left = count - len(groups)
        items_left = len(sentences) - index - 1
        if groups_left > 1 and (size >= remaining_size / groups_left or items_left == groups_left - 1):
            groups.append(" ".join(current))
            remaining_size -= size
            current, size = [], 0
    if current:
        groups.append(" ".join(current))
    return groups


def _plan(params):
    count = math.ceil(params.target_duration_minutes / params.chapter_duration_minutes)
    if params.video_script.strip():
        return [{"title": f"Chapter {i}", "script": text}
                for i, text in enumerate(_split_script(params.video_script, count), 1)]
    prompt = (
        f"Plan a coherent video about {params.video_subject!r}. "
        f"Language: {params.video_language or 'same as the topic'}. "
        f"Create exactly {count} chapters, together approximately "
        f"{params.target_duration_minutes} minutes. Each chapter must advance the story, "
        "without repeating introductions or conclusions. Return ONLY a JSON array of "
        "objects with nonempty string fields 'title' and 'summary'. "
        f"Additional requirements: {params.video_script_prompt}\n"
        f"Editorial guidance: {params.custom_system_prompt}"
    )
    response = llm._generate_response(prompt=prompt)
    try:
        chapters = json.loads(llm._strip_code_fence(response))
    except (ValueError, TypeError) as exc:
        raise ChapterError("The language model returned an invalid chapter plan; retry the task") from exc
    if (not isinstance(chapters, list) or len(chapters) != count
            or any(not isinstance(chapter, dict)
                   or any(not isinstance(chapter.get(key), str) or not chapter[key].strip()
                          for key in ("title", "summary")) for chapter in chapters)):
        raise ChapterError("The language model returned an incomplete chapter plan")
    return [{"title": chapter["title"].strip(), "summary": chapter["summary"].strip()}
            for chapter in chapters]


def _audio_plan(params, duration):
    count = math.ceil(duration / (params.chapter_duration_minutes * 60))
    scripts = _split_script(params.video_script, count) if params.video_script.strip() else []
    if scripts and len(scripts) != count:
        raise ChapterError("The supplied transcript is too short for the number of audio chapters")
    # Balanced, sample-aligned boundaries avoid an extra tiny chapter at the end.
    samples = round(duration * 48000)
    return [{"title": f"Chapter {i + 1}", "script": scripts[i] if scripts else "",
             "start": (samples * i // count) / 48000,
             "end": (samples * (i + 1) // count) / 48000}
            for i in range(count)]


def _extract_audio(source, directory, chapter):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "narration.wav"
    temporary = directory / ".narration.partial.wav"
    try:
        result = subprocess.run(
            [utils.get_ffmpeg_binary(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-protocol_whitelist", "file,pipe", "-i", str(source),
             "-ss", str(chapter["start"]), "-t", str(chapter["end"] - chapter["start"]),
             "-map", "0:a:0", "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le", str(temporary)],
            capture_output=True, text=True, timeout=600, check=False,
        )
        if result.returncode:
            raise ChapterError("Could not split imported narration into chapters")
        os.replace(temporary, target)
        return str(target)
    finally:
        temporary.unlink(missing_ok=True)


def _transcribe_audio(audio_file):
    transcript_file = str(Path(audio_file).with_suffix(".transcript.srt"))
    subtitle.create(audio_file=audio_file, subtitle_file=transcript_file)
    text = " ".join(cue[2] for cue in subtitle.file_to_subtitles(transcript_file)).strip()
    if not text:
        raise ChapterError("Could not transcribe imported narration; check Whisper or supply its transcript")
    return text


def _script(params, chapters, index):
    chapter = chapters[index]
    # Leave headroom for pauses, transitions and slower narration. Duration is a target.
    minutes = params.target_duration_minutes / len(chapters)
    words = max(50, round(minutes * 120 * params.voice_rate))
    outline = "\n".join(f"{i + 1}. {item['title']}" for i, item in enumerate(chapters))
    requirements = (
        f"Write ONLY the spoken narration for chapter {index + 1}/{len(chapters)} "
        f"of a single continuous video. Topic: {params.video_subject}.\n"
        f"Whole outline:\n{outline}\n"
        f"This chapter: {chapter['title']}. {chapter.get('summary', '')}\n"
        f"Aim for {words} spoken words (about {minutes:.1f} minutes). "
        "Do not include headings, production directions or announce chapter numbers. "
        "Use natural transitions. Only the first chapter introduces the video; "
        "only the last concludes it. Avoid repeating earlier chapters.\n"
        f"Previous chapter ending (context only, do not repeat): "
        f"{chapters[index - 1].get('script', '')[-1200:] if index else ''}"
    )
    script = llm.generate_script(
        video_subject=requirements,
        language=params.video_language,
        paragraph_number=min(10, max(1, round(minutes * 2))),
        video_script_prompt=params.video_script_prompt,
        custom_system_prompt=params.custom_system_prompt,
    )
    if not script or not script.strip():
        raise ChapterError(f"Could not generate the script for chapter {index + 1}")
    return script.strip()


def _duration(file):
    with VideoFileClip(str(file)) as clip:
        duration = float(clip.duration or 0)
        if not math.isfinite(duration) or duration <= 0 or clip.audio is None:
            raise ChapterError(f"Invalid chapter video: {file.name}")
        # Probe both ends, not just the container header.
        clip.get_frame(0)
        clip.get_frame(max(0, duration - 0.1))
        return duration


def _join(directory, inputs, expected_duration):
    """The same pipeline/settings produce compatible streams; mux without loading all frames."""
    listing = directory / "chapters.ffconcat"
    listing.write_text("ffconcat version 1.0\n" + "".join(
        "file '" + str(file.relative_to(directory)).replace("\\", "/").replace("'", "'\\''") + "'\n"
        for file in inputs
    ), encoding="utf-8")
    temporary = directory / "long-video.partial.mp4"
    output = directory / "final-1.mp4"
    try:
        result = subprocess.run(
            [utils.get_ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "concat", "-safe", "0", "-i", str(listing),
             "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
             "-movflags", "+faststart", str(temporary)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise ChapterError(f"Could not join chapters: {result.stderr[-1500:]}")
        actual_duration = _duration(temporary)
        if abs(actual_duration - expected_duration) > max(1, len(inputs) * 0.15):
            raise ChapterError("Joined video duration does not match completed chapters")
        if actual_duration > 1800.5:
            raise ChapterError("Narration exceeds the 30-minute limit; use a shorter script or duration target")
        os.replace(temporary, output)
        return output, actual_duration
    finally:
        temporary.unlink(missing_ok=True)


def _migrate_image_provider(params, references, directory, manifest):
    """Verify the original root fingerprint before allowing an image-provider migration."""
    if params.video_source != "mixed" or not (directory / "script.json").is_file():
        return False
    saved = json.loads((directory / "script.json").read_text(encoding="utf-8"))["params"]
    if saved.get("mixed_image_provider", "openai") not in {"openai", "openai_flow", "flow_browser", "none", "ai33", "runware", "grok"}:
        return False
    original = dict(saved)
    original.pop("mixed_resume", None)
    original.pop("mixed_resume_subtitle_style", None)
    original.pop("mixed_grok_unlimited", None)
    if original.get("custom_audio_file"):
        original["custom_audio_file"] = "<external-narration>"
    candidates = [original]
    normalized = dict(original)
    for name in ("subtitle_soft_shadow", "subtitle_max_lines"):
        if not normalized.get(name):
            normalized.pop(name, None)
    if not normalized.get("skills_enabled") or not normalized.get("skill_snapshot"):
        for key in ("skills_enabled", "skill_ids", "skill_snapshot"):
            normalized.pop(key, None)
    candidates.append(dict(normalized))
    if normalized.get("mixed_image_provider") != "runware":
        for key in ("runware_model", "runware_steps", "runware_size", "mixed_use_runware"):
            normalized.pop(key, None)
    for key in ("grok_model", "mixed_use_grok"):
        if normalized.get("mixed_image_provider") != "grok":
            normalized.pop(key, None)
    candidates.append(normalized)
    if not any(hashlib.sha256(json.dumps({"params": candidate, "references": references}, sort_keys=True).encode()).hexdigest()
               == manifest.get("fingerprint") for candidate in candidates):
        return False
    before = VideoParams.model_validate(saved).model_dump(mode="json")
    after = params.model_dump(mode="json")
    for key in ("mixed_resume", "mixed_grok_unlimited", "mixed_image_provider", "mixed_use_grok", "grok_model", "mixed_use_ai33", "mixed_use_runware", "mixed_use_grok", "grok_model", "runware_model", "runware_steps", "runware_size", "ai33_model", "ai33_resolution", "ai33_quality", "ai33_max_credits"):
        before.pop(key, None)
        after.pop(key, None)
    if before != after:
        return False
    # One-time original backup; never move/delete existing media.
    backup = directory / "ai33-migration-backup"
    backup.mkdir(exist_ok=True)
    for name in ("script.json", "chapters.json"):
        target = backup / name
        if not target.exists():
            target.write_bytes((directory / name).read_bytes())
    manifest["original_fingerprint"] = manifest["fingerprint"]
    manifest["fingerprint"] = _fingerprint(params, references)
    manifest["continuation_image_provider"] = params.mixed_image_provider + "_image"
    return True


def _run_locked(task_id, params, directory, render_chapter, references, audio_file=None, audio_duration=None):
    checkpoint = directory / "chapters.json"
    fingerprint = _fingerprint(params, references)
    if checkpoint.exists():
        manifest = json.loads(checkpoint.read_text(encoding="utf-8"))
        if manifest.get("version") == 1 and manifest.get("fingerprint") != fingerprint:
            if _migrate_image_provider(params, references, directory, manifest):
                _save(checkpoint, manifest)
        if manifest.get("version") != 1 or manifest.get("fingerprint") != fingerprint:
            raise ChapterError("Checkpoint settings differ; restore the original settings or use a new task ID")
    else:
        chapters = _audio_plan(params, audio_duration) if audio_file else _plan(params)
        manifest = {"version": 1, "fingerprint": fingerprint, "chapters": chapters}
        _save(checkpoint, manifest)
    chapters = manifest["chapters"]
    task_artifacts.write_script_data(task_id, {
        "script": "\n\n".join(chapter.get("script", "") for chapter in chapters),
        "search_terms": params.video_terms or [], "params": params.model_dump(mode="json"),
    })
    inputs, duration = [], 0.0
    for index, chapter in enumerate(chapters):
        sm.state.update_task(task_id, progress=5 + int(85 * index / len(chapters)),
                             current_chapter=index + 1, chapter_count=len(chapters),
                             chapter_title=chapter["title"])
        generation_progress.stage("chapter")
        child_id = f"{task_id}/chapters/{index + 1:03d}"
        # Derived paths, never paths supplied by the checkpoint.
        file = directory / "chapters" / f"{index + 1:03d}" / "final-1.mp4"
        reusable = (file.is_file() and chapter.get("sha256") == _digest(file))
        if not reusable:
            chapter_audio = _extract_audio(audio_file, file.parent, chapter) if audio_file else None
            if not chapter.get("script"):
                chapter["script"] = _transcribe_audio(chapter_audio) if chapter_audio else _script(params, chapters, index)
                _save(checkpoint, manifest)
            child_params = params.model_copy(deep=True, update={
                "long_form": False, "video_script": chapter["script"],
                "video_subject": f"{params.video_subject} — {chapter['title']}",
                # Generate search terms independently for each chapter by default.
                "video_terms": params.video_terms,
                "custom_audio_file": chapter_audio,
            })
            if params.video_source in {"mixed", "ai33_image", "grok_image", "runware_image"}:
                from app.services import mixed_materials

                spent_elsewhere = sum(
                    mixed_materials.image_requests(f"{task_id}/chapters/{other + 1:03d}")
                    for other in range(len(chapters)) if other != index
                )
                child_params.mixed_is_chapter = True
                child_params.mixed_total_duration = audio_duration or 0
                child_params.mixed_previous_sources = []
                for previous_index in range(index):
                    previous_file = directory / "chapters" / f"{previous_index + 1:03d}" / "mixed-scenes.json"
                    if previous_file.exists():
                        previous_manifest = json.loads(previous_file.read_text(encoding="utf-8"))
                        child_params.mixed_previous_sources.extend(s["provenance"] for s in previous_manifest.get("scenes", []) if s.get("provenance"))
                child_params.mixed_timeline_offset = params.mixed_timeline_offset + duration
                child_params.mixed_max_images = max(0, params.mixed_max_images - spent_elsewhere)
                child_params.mixed_resume = (Path(utils.task_dir(child_id)) / "mixed-scenes.json").is_file()
            with generation_progress.task_scope(child_id):
                result = render_chapter(child_id, child_params)
            if not result or not result.get("videos") or result.get("state") == const.TASK_STATE_FAILED:
                message = (result or {}).get("error", "chapter generation failed")
                raise ChapterError(f"Chapter {index + 1}: {message}. Resume using the same task ID")
            generated = Path(result["videos"][0]).resolve()
            if generated != file.resolve():
                raise ChapterError("Chapter renderer returned an unexpected output path")
            chapter["duration"] = _duration(file)
            chapter["sha256"] = _digest(file)
            chapter["warnings"] = result.get("warnings") or []
            _save(checkpoint, manifest)
        else:
            chapter["duration"] = _duration(file)
        inputs.append(file)
        duration += chapter["duration"]
        if duration > 1800.5:
            raise ChapterError("Narration exceeds 30 minutes; use a shorter script or duration target with a new task ID")
    sm.state.update_task(task_id, progress=92)
    generation_progress.stage("joining_chapters")
    output, actual_duration = _join(directory, inputs, duration)
    manifest["duration"] = actual_duration
    manifest["complete"] = True
    _save(checkpoint, manifest)
    result = {"videos": [str(output)], "combined_videos": [],
              "script": "\n\n".join(chapter["script"] for chapter in chapters),
              "audio_duration": actual_duration, "chapter_count": len(chapters),
              "chapter_titles": [chapter["title"] for chapter in chapters],
              "warnings": [dict(warning, chapter_index=index + 1)
                           for index, chapter in enumerate(chapters)
                           for warning in chapter.get("warnings", [])] or None}
    if params.video_source in {"mixed", "ai33_image", "grok_image", "runware_image"}:
        from app.services import mixed_materials

        result["mixed_image_requests"] = sum(
            mixed_materials.image_requests(f"{task_id}/chapters/{index + 1:03d}")
            for index in range(len(chapters))
        )
    task_artifacts.patch_script_data(task_id, script=result["script"])
    # Chapters are never automatically published to social networks.
    sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, **result)
    return result


def run(task_id, params, *, render_chapter, reference_audio=None, prompt_audio=None, prompt_text="",
        allow_server_file_input=False):
    validate(params)
    directory = Path(utils.task_dir(task_id)).resolve()
    references = [hashlib.sha256(value or b"").hexdigest()
                  for value in (reference_audio, prompt_audio, prompt_text.encode())]
    lock = FileLock(str(directory / "chapters.lock"))
    try:
        with lock.acquire(timeout=0):
            sm.state.update_task(task_id, progress=2, failed_stage=None, error=None,
                                 videos=[], combined_videos=[], generation_started_at=time.time())
            generation_progress.stage("planning_chapters")
            audio_file, duration = None, None
            if params.custom_audio_file:
                from app.services.task import resolve_custom_audio_file

                audio_file = resolve_custom_audio_file(
                    task_id, params.custom_audio_file, allow_server_file_input=allow_server_file_input,
                )
                if os.path.getsize(audio_file) > narration.MAX_NARRATION_UPLOAD_BYTES:
                    raise ChapterError("Narration file exceeds the 500 MB limit")
                duration = voice.get_audio_duration(audio_file)
                if not math.isfinite(duration) or not 0 < duration <= 1800:
                    raise ChapterError("Imported chapter narration must be nonempty and at most 30 minutes")
                references.append(_digest(audio_file))
            return _run_locked(task_id, params, directory, render_chapter, references, audio_file, duration)
    except Timeout:
        # A duplicate submission must not mark the active owner's task as failed.
        return sm.state.get_task(task_id) or {"task_id": task_id, "state": const.TASK_STATE_PROCESSING}
