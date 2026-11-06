import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from filelock import FileLock
from pydantic import ValidationError

from app.models import const
from app.models.schema import VideoParams
from app.services import long_form as lf
from app.services import task as tm
from app.services.state import MemoryState


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def task_dir(task_id=""):
        directory = tmp_path / task_id
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    monkeypatch.setattr(lf.utils, "task_dir", task_dir)
    state = MemoryState()
    monkeypatch.setattr(lf.sm, "state", state)
    monkeypatch.setattr(lf, "_duration", lambda file: 2.0)
    join = Mock(side_effect=lambda directory, inputs, duration: (directory / "long-video.mp4", duration))
    monkeypatch.setattr(lf, "_join", join)
    params = VideoParams(video_subject="Coffee", video_script="First chapter. Second chapter.",
                         voice_name="pt-BR-AntonioNeural-Male", video_source="local",
                         long_form=True, target_duration_minutes=2, chapter_duration_minutes=1)

    def render(task_id, params, **kwargs):
        file = Path(task_dir(task_id)) / "final-1.mp4"
        file.write_bytes(params.video_script.encode())
        return {"videos": [str(file)]}

    renderer = Mock(side_effect=render)
    return tmp_path, params, renderer, state, join


def test_chapters_complete_in_order_with_independent_scripts(setup):
    root, params, renderer, state, join = setup
    result = lf.run("job", params, render_chapter=renderer)
    assert result["chapter_count"] == 2
    assert result["script"] == "First chapter.\n\nSecond chapter."
    assert state.get_task("job")["state"] == const.TASK_STATE_COMPLETE
    assert [call.args[1].video_script for call in renderer.call_args_list] == ["First chapter.", "Second chapter."]
    assert all(not call.args[1].long_form for call in renderer.call_args_list)
    assert [p.parent.name for p in join.call_args.args[1]] == ["001", "002"]
    assert json.loads((root / "job/chapters.json").read_text())["complete"]
    # Never mutate the original request when preparing chapter inputs.
    assert params.long_form and params.video_script == "First chapter. Second chapter."


def test_failure_then_resume_reuses_completed_chapter_after_state_loss(setup, monkeypatch):
    root, params, renderer, state, join = setup
    real_render = renderer.side_effect

    def interrupt(task_id, chapter_params, **kwargs):
        if task_id.endswith("002"):
            return {"state": const.TASK_STATE_FAILED, "error": "provider unavailable"}
        return real_render(task_id, chapter_params)

    renderer.side_effect = interrupt
    with pytest.raises(lf.ChapterError, match="Chapter 2: provider unavailable"):
        lf.run("job", params, render_chapter=renderer)
    join.assert_not_called()
    checkpoint = json.loads((root / "job/chapters.json").read_text())
    assert checkpoint["chapters"][0]["sha256"]
    assert not checkpoint["chapters"][1].get("sha256")
    monkeypatch.setattr(lf.sm, "state", MemoryState())
    renderer.reset_mock()
    renderer.side_effect = real_render
    result = lf.run("job", params, render_chapter=renderer)
    assert result["chapter_count"] == 2
    assert renderer.call_count == 1
    assert renderer.call_args.args[0].endswith("002")


@pytest.mark.parametrize("change", ["missing", "modified"])
def test_damaged_chapter_is_regenerated(setup, change):
    root, params, renderer, _, _ = setup
    lf.run("job", params, render_chapter=renderer)
    file = root / "job/chapters/001/final-1.mp4"
    if change == "missing":
        file.unlink()
    else:
        file.write_bytes(b"truncated video")
    renderer.reset_mock()
    lf.run("job", params, render_chapter=renderer)
    assert renderer.call_count == 1
    assert renderer.call_args.args[0].endswith("001")


def test_changed_settings_or_reference_audio_cannot_mix_outputs(setup):
    _, params, renderer, _, _ = setup
    lf.run("job", params, render_chapter=renderer, reference_audio=b"one")
    renderer.reset_mock()
    with pytest.raises(lf.ChapterError, match="settings differ"):
        lf.run("job", params, render_chapter=renderer, reference_audio=b"two")
    with pytest.raises(lf.ChapterError, match="settings differ"):
        lf.run("job", params.model_copy(update={"voice_rate": 1.1}), render_chapter=renderer)
    renderer.assert_not_called()


def test_outline_and_each_script_are_persisted_before_render(setup, monkeypatch):
    root, params, renderer, _, _ = setup
    params.video_script = ""
    plan = Mock(return_value='[{"title":"Origins","summary":"History"},{"title":"Today","summary":"Culture"}]')
    script = Mock(side_effect=["A history of coffee.", "Coffee today."])
    monkeypatch.setattr(lf.llm, "_generate_response", plan)
    monkeypatch.setattr(lf.llm, "generate_script", script)
    real_render = renderer.side_effect

    def inspect(task_id, chapter_params):
        manifest = json.loads((root / "job/chapters.json").read_text())
        assert any(c.get("script") == chapter_params.video_script for c in manifest["chapters"])
        return real_render(task_id, chapter_params)

    renderer.side_effect = inspect
    result = lf.run("job", params, render_chapter=renderer)
    assert result["chapter_titles"] == ["Origins", "Today"]
    assert script.call_count == 2
    assert "120 spoken words" in script.call_args_list[0].kwargs["video_subject"]
    assert "A history of coffee." in script.call_args_list[1].kwargs["video_subject"]
    lf.run("job", params, render_chapter=renderer)
    assert plan.call_count == 1 and script.call_count == 2


@pytest.mark.parametrize("response", ['Error: denied', '[]', '[{"title":"A"}]', '{}', 'null'])
def test_invalid_llm_plan_never_starts_paid_video_generation(setup, monkeypatch, response):
    _, params, renderer, _, _ = setup
    params.video_script = ""
    monkeypatch.setattr(lf.llm, "_generate_response", lambda **kwargs: response)
    with pytest.raises(lf.ChapterError):
        lf.run("job", params, render_chapter=renderer)
    renderer.assert_not_called()


@pytest.mark.parametrize("update", [{"video_count": 2},
                                    {"voice_name": ""}, {"video_source": "loomloom"},
                                    {"voice_rate": 0}])
def test_incompatible_inputs_fail_before_render(setup, update):
    _, params, renderer, _, _ = setup
    with pytest.raises(ValueError):
        lf.run("job", params.model_copy(update=update), render_chapter=renderer)
    renderer.assert_not_called()


def test_duplicate_attempt_does_not_overwrite_running_task(setup):
    root, params, renderer, state, _ = setup
    (root / "job").mkdir()
    state.update_task("job", progress=47)
    with FileLock(str(root / "job/chapters.lock")):
        result = lf.run("job", params, render_chapter=renderer)
    assert result["progress"] == 47
    renderer.assert_not_called()


def test_join_failure_keeps_chapters_for_retry(setup):
    _, params, renderer, _, join = setup
    join.side_effect = lf.ChapterError("disk full")
    with pytest.raises(lf.ChapterError, match="disk full"):
        lf.run("job", params, render_chapter=renderer)
    renderer.reset_mock()
    join.side_effect = lambda directory, inputs, duration: (directory / "long-video.mp4", duration)
    lf.run("job", params, render_chapter=renderer)
    renderer.assert_not_called()


def test_pipeline_dispatch_and_failure_status(setup, monkeypatch):
    _, params, renderer, state, _ = setup
    monkeypatch.setattr(tm, "_run_pipeline", renderer)
    result = tm.start("job", params)
    assert result["chapter_count"] == 2
    assert all(call.kwargs["publish"] is False for call in renderer.call_args_list)
    result = tm.start("other", params, stop_at="audio")
    assert result["state"] == const.TASK_STATE_FAILED
    assert "stop_at=video" in result["error"]
    assert state.get_task("other")["state"] == const.TASK_STATE_FAILED


def test_duration_boundaries():
    for value in (0, 31):
        with pytest.raises(ValidationError):
            VideoParams(video_subject="test", target_duration_minutes=value)
    with pytest.raises(ValidationError):
        VideoParams(video_subject="test", chapter_duration_minutes=6)


@pytest.mark.parametrize("text", ["First. Second. Third. Fourth.", "一。二。三。四。", "one two three four five"])
def test_split_preserves_all_text_in_order(text):
    parts = lf._split_script(text, 3)
    assert len(parts) == 3
    assert "".join("".join(parts).split()) == "".join(text.split())


def test_real_ffmpeg_join_has_video_audio_and_expected_duration(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is not installed")
    inputs = []
    for i, color in enumerate(("red", "blue")):
        file = tmp_path / f"chapter-{i}.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=24:d=1",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(file)], check=True)
        inputs.append(file)
    output, duration = lf._join(tmp_path, inputs, 2)
    assert output.is_file() and abs(duration - 2) < 0.15
    with lf.VideoFileClip(str(output)) as clip:
        assert clip.audio is not None
        assert clip.get_frame(0.25)[0, 0, 0] > 200
        assert clip.get_frame(1.25)[0, 0, 2] > 200
    assert not (tmp_path / "long-video.partial.mp4").exists()


def test_cli_passes_chapter_settings_to_video_params():
    from cli import parse_args, build_video_params

    args = parse_args(["--video-subject", "Coffee", "--long-form",
                       "--target-duration-minutes", "30", "--chapter-duration-minutes", "5"])
    params = build_video_params(args)
    assert params.long_form
    assert params.target_duration_minutes == 30
    assert params.chapter_duration_minutes == 5


def test_overlong_narration_stops_without_cutting_or_joining(setup, monkeypatch):
    _, params, renderer, _, join = setup
    monkeypatch.setattr(lf, "_duration", lambda file: 950)
    with pytest.raises(lf.ChapterError, match="exceeds 30 minutes"):
        lf.run("job", params, render_chapter=renderer)
    join.assert_not_called()


@pytest.mark.parametrize("external_audio", [False, True])
def test_real_chapter_pipeline_renders_and_joins_without_auto_publishing(tmp_path, monkeypatch, external_audio):
    """Exercise the existing renderer, replacing only external narration/material providers."""
    from app.models.schema import VideoAspect, VideoConcatMode

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is not installed")

    def task_dir(task_id=""):
        directory = tmp_path / "tasks" / task_id
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    monkeypatch.setattr(lf.utils, "task_dir", task_dir)
    monkeypatch.setattr(lf.sm, "state", MemoryState())
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (160, 90))
    source = tmp_path / "source.mp4"
    audio = tmp_path / "narration.mp3"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=green:s=160x90:r=30:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)], check=True)
    if not external_audio:
        monkeypatch.setattr(tm, "generate_audio", lambda *args, **kwargs: (str(audio), 1, None))
    else:
        monkeypatch.setattr(tm.voice, "tts", Mock(side_effect=AssertionError("TTS must not be called")))
    monkeypatch.setattr(tm, "get_video_materials", lambda *args, **kwargs: [str(source)])
    publishing = Mock(return_value=True)
    monkeypatch.setattr(tm.upload_post.upload_post_service, "is_configured", publishing)
    params = VideoParams(video_subject="Coffee", video_script="First chapter. Second chapter.",
                         voice_name="pt-BR-AntonioNeural-Male", video_source="local",
                         subtitle_enabled=False, bgm_type="", n_threads=1,
                         video_concat_mode=VideoConcatMode.sequential,
                         long_form=True, target_duration_minutes=2, chapter_duration_minutes=1)
    if external_audio:
        params.custom_audio_file = str(audio)
        params.voice_name = ""
    result = tm.start("integration", params, allow_server_file_input=external_audio)
    assert result.get("videos"), result
    assert Path(result["videos"][0]).name == "final-1.mp4"
    assert result["chapter_count"] == (1 if external_audio else 2)
    assert abs(lf._duration(Path(result["videos"][0])) - (1 if external_audio else 2)) < 0.2
    assert lf.sm.state.get_task("integration")["state"] == const.TASK_STATE_COMPLETE
    manifest = json.loads((tmp_path / "tasks/integration/script.json").read_text())
    assert manifest["params"]["long_form"]
    assert manifest["script"] == ("First chapter. Second chapter." if external_audio else "First chapter.\n\nSecond chapter.")
    publishing.assert_not_called()


def _external_audio(setup, monkeypatch):
    root, params, renderer, state, join = setup
    parent = root / "job"
    parent.mkdir()
    source = parent / "recording.wav"
    source.write_bytes(b"the original recording")
    params.custom_audio_file = str(source)
    params.voice_name = ""
    params.subtitle_enabled = False
    monkeypatch.setattr(lf.voice, "get_audio_duration", lambda file: 120)

    def extract(source, directory, chapter):
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / "narration.wav"
        output.write_bytes(b"audio chunk")
        return str(output)

    splitting = Mock(side_effect=extract)
    monkeypatch.setattr(lf, "_extract_audio", splitting)
    generating = Mock(side_effect=AssertionError("Imported narration must never generate a new script"))
    monkeypatch.setattr(lf.llm, "generate_script", generating)
    return source, params, renderer, splitting, generating


def test_imported_narration_splits_by_actual_duration_without_tts(setup, monkeypatch):
    source, params, renderer, splitting, generating = _external_audio(setup, monkeypatch)
    # The slider target must not stretch, truncate or replace imported narration.
    params.target_duration_minutes = 30
    result = lf.run("job", params, render_chapter=renderer)
    assert result["chapter_count"] == 2
    assert splitting.call_count == 2
    assert [(c.args[2]["start"], c.args[2]["end"]) for c in splitting.call_args_list] == [(0, 60), (60, 120)]
    assert all(c.args[1].custom_audio_file.endswith("narration.wav") for c in renderer.call_args_list)
    assert source.read_bytes() == b"the original recording"
    generating.assert_not_called()


def test_same_audio_from_new_path_resumes_but_changed_audio_is_rejected(setup, monkeypatch):
    source, params, renderer, splitting, _ = _external_audio(setup, monkeypatch)
    lf.run("job", params, render_chapter=renderer)
    renderer.reset_mock()
    splitting.reset_mock()
    replacement = source.with_name("uploaded-again.wav")
    replacement.write_bytes(source.read_bytes())
    params.custom_audio_file = str(replacement)
    lf.run("job", params, render_chapter=renderer)
    renderer.assert_not_called()
    splitting.assert_not_called()
    replacement.write_bytes(b"a different narration")
    with pytest.raises(lf.ChapterError, match="settings differ"):
        lf.run("job", params, render_chapter=renderer)


def test_imported_audio_can_transcribe_each_chapter_with_explicit_whisper(setup, monkeypatch):
    _, params, renderer, _, generating = _external_audio(setup, monkeypatch)
    params.video_script = ""
    monkeypatch.setitem(lf.config.app, "subtitle_provider", "whisper")
    transcript = Mock(side_effect=["First spoken chapter.", "Second spoken chapter."])
    monkeypatch.setattr(lf, "_transcribe_audio", transcript)
    lf.run("job", params, render_chapter=renderer)
    assert transcript.call_count == 2
    assert [c.args[1].video_script for c in renderer.call_args_list] == ["First spoken chapter.", "Second spoken chapter."]
    generating.assert_not_called()


def test_imported_audio_without_transcript_requires_explicit_whisper(setup, monkeypatch):
    _, params, renderer, _, _ = _external_audio(setup, monkeypatch)
    params.video_script = ""
    monkeypatch.setitem(lf.config.app, "subtitle_provider", "edge")
    with pytest.raises(ValueError, match="transcript or select Whisper"):
        lf.run("job", params, render_chapter=renderer)
    renderer.assert_not_called()


def test_imported_audio_subtitles_require_whisper(setup, monkeypatch):
    _, params, renderer, _, _ = _external_audio(setup, monkeypatch)
    params.subtitle_enabled = True
    monkeypatch.setitem(lf.config.app, "subtitle_provider", "edge")
    with pytest.raises(ValueError, match="Whisper for subtitles"):
        lf.run("job", params, render_chapter=renderer)
    renderer.assert_not_called()


@pytest.mark.parametrize("duration", [0, 1801, float("inf")])
def test_overlong_or_invalid_recording_fails_before_render(setup, monkeypatch, duration):
    _, params, renderer, splitting, _ = _external_audio(setup, monkeypatch)
    monkeypatch.setattr(lf.voice, "get_audio_duration", lambda file: duration)
    with pytest.raises(lf.ChapterError, match="at most 30 minutes"):
        lf.run("job", params, render_chapter=renderer)
    splitting.assert_not_called()
    renderer.assert_not_called()


def test_imported_audio_keeps_task_directory_boundary(setup, monkeypatch):
    source, params, renderer, splitting, _ = _external_audio(setup, monkeypatch)
    outside = source.parent.parent / "other-recording.wav"
    outside.write_bytes(source.read_bytes())
    params.custom_audio_file = str(outside)
    with pytest.raises(ValueError, match="current task directory"):
        lf.run("job", params, render_chapter=renderer)
    renderer.assert_not_called()
    splitting.assert_not_called()


def test_imported_chapter_subtitles_preserve_whisper_words(setup, monkeypatch):
    _, params, _, _, _ = setup
    params.subtitle_enabled = True
    params.custom_audio_file = "narration.wav"
    monkeypatch.setitem(lf.config.app, "subtitle_provider", "whisper")

    def transcribe(**kwargs):
        Path(kwargs["subtitle_file"]).write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nActual spoken words.\n\n", encoding="utf-8",
        )

    monkeypatch.setattr(tm.subtitle, "create", transcribe)
    correction = Mock()
    monkeypatch.setattr(tm.subtitle, "correct", correction)
    file = tm.generate_subtitle("job", params, "Approximate transcript section.", None,
                                "narration.wav", correct_to_script=False)
    assert "Actual spoken words." in Path(file).read_text()
    correction.assert_not_called()


def test_mixed_image_budget_is_shared_across_chapters(setup, monkeypatch):
    from app.services import mixed_materials
    root, params, renderer, _, _ = setup
    params.video_source = "mixed"
    params.mixed_max_images = 2
    monkeypatch.setattr(mixed_materials, "validate", lambda *args, **kwargs: None)
    render_original = renderer.side_effect
    budgets, offsets = [], []

    def render(task_id, chapter_params):
        offsets.append(chapter_params.mixed_timeline_offset)
        budgets.append(chapter_params.mixed_max_images)
        result = render_original(task_id, chapter_params)
        (root / task_id / "mixed-scenes.json").write_text(json.dumps({"image_requests": 1}))
        return result

    renderer.side_effect = render
    lf.run("job", params, render_chapter=renderer)
    assert budgets == [2, 1]
    assert offsets == [0, 2.0]
    assert params.mixed_max_images == 2
