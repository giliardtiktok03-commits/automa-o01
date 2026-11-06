import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import mixed_materials as mixed
from app.services.state import MemoryState


SCRIPT = "Hoje preparamos café. As plantações dependiam de pessoas escravizadas no século XIX. Hoje embalamos os grãos."


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def task_dir(task_id=""):
        path = tmp_path / task_id
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    monkeypatch.setattr(mixed.utils, "task_dir", task_dir)
    monkeypatch.setattr(mixed.sm, "state", MemoryState())
    monkeypatch.setattr(mixed.config, "app", {"pexels_api_keys": ["test-pexels"], "pixabay_api_keys": ["test-pixabay"],
                                             "openai_image_base_url": "https://images.example.test/v1", "openai_image_model": "test-model"})
    folder = Path(task_dir("job"))
    subtitles = folder / "subtitle.srt"
    subtitles.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\nHoje preparamos café.\n\n"
        "2\n00:00:10,000 --> 00:00:20,000\nAs plantações dependiam de pessoas escravizadas no século XIX.\n\n"
        "3\n00:00:20,000 --> 00:00:30,000\nHoje embalamos os grãos.\n\n", encoding="utf-8")
    choices = [{"id": i, "source": "stock", "context": "current", "period": "present day" if i != 2 else "19th century",
                "location": "Brazil", "search_query": f"coffee scene {i}",
                "image_prompt": f"Illustrate coffee scene {i} in its narrative context.", "reason": "Narrative fit"}
               for i in (1, 2, 3)]
    model = Mock(return_value=json.dumps(choices))
    monkeypatch.setattr(mixed.llm, "_generate_response", model)
    search = Mock(side_effect=lambda provider, *args: [MaterialInfo(provider=provider, url=f"https://stock.example.test/{provider}.mp4", duration=10)])
    monkeypatch.setattr(mixed.material, "_search_videos_with_cache", search)

    def save(url, directory):
        path = Path(directory) / (url.rsplit('/', 1)[-1])
        path.write_bytes(b"stock clip")
        return str(path)
    monkeypatch.setattr(mixed.material, "save_video", save)

    def image(**kwargs):
        path = Path(kwargs["save_dir"]) / "generated.png"
        path.write_bytes(b"paid image")
        return [MaterialInfo(provider="openai_image", url=str(path), duration=1)]
    images = Mock(side_effect=image)
    monkeypatch.setattr(mixed.material, "generate_images_openai", images)
    monkeypatch.setattr(mixed.material, "_render_openai_image_video", lambda *args, **kwargs: "image-clip.mp4")

    def render(source, output, frames, params, **kwargs):
        output.write_bytes((str(source)+str(frames)).encode())
    rendering = Mock(side_effect=render)
    monkeypatch.setattr(mixed, "render", rendering)
    params = VideoParams(video_subject="Café", video_script=SCRIPT, video_source="mixed", mixed_visual_validation=False, mixed_scene_duration=5)
    return folder, subtitles, params, model, search, images, rendering


def test_mixed_uses_pexels_historical_illustration_and_pixabay_in_order(setup):
    folder, subtitles, params, model, search, images, rendering = setup
    result = mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert [Path(file).name for file in result] == ["scene-001.mp4", "scene-002.mp4", "scene-003.mp4"]
    assert [call.args[0] for call in search.call_args_list] == ["pexels", "pixabay"]
    assert images.call_count == 1
    prompt = images.call_args.kwargs["search_term"]
    assert "pessoas escravizadas" in prompt
    assert "19th century" in prompt and "Brazil" in prompt
    assert "no contemporary buildings" in prompt
    manifest = json.loads((folder / "mixed-scenes.json").read_text())
    assert manifest["timing"] == "subtitles"
    assert manifest["image_requests"] == 1
    assert [scene["provenance"]["provider"] for scene in manifest["scenes"]] == ["pexels", "openai_image", "pixabay"]
    assert [call.args[2] for call in rendering.call_args_list] == [300, 300, 300]
    assert model.call_count == 1


def test_completed_scene_checkpoint_is_reused_without_new_image_requests(setup):
    _, subtitles, params, model, search, images, rendering = setup
    first = mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    for mock in (model, search, images, rendering):
        mock.reset_mock()
    assert mixed.prepare("job", params, SCRIPT, 30, str(subtitles)) == first
    for mock in (model, search, images, rendering):
        mock.assert_not_called()


def test_image_cap_is_checked_before_downloading_or_ordering_images(setup):
    _, subtitles, params, _, search, images, _ = setup
    params.mixed_max_images = 0
    with pytest.raises(mixed.MixedError, match="exceeds"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    search.assert_not_called()
    images.assert_not_called()


def test_unknown_paid_result_cannot_be_automatically_ordered_again(setup):
    _, subtitles, params, _, _, images, _ = setup
    images.side_effect = mixed.material.OpenAIImagePaidResultError("unknown response")
    with pytest.raises(mixed.material.OpenAIImagePaidResultError):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    with pytest.raises(mixed.MixedError, match="unknown result"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert images.call_count == 1
    assert mixed.image_requests("job") == 1


def test_render_failure_reuses_the_saved_paid_image(setup, monkeypatch):
    _, subtitles, params, _, _, images, _ = setup
    conversion = Mock(side_effect=[None, "image-clip.mp4"])
    monkeypatch.setattr(mixed.material, "_render_openai_image_video", conversion)
    with pytest.raises(mixed.material.OpenAIImagePaidResultError):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert len(mixed.prepare("job", params, SCRIPT, 30, str(subtitles))) == 3
    assert images.call_count == 1


def test_a_failed_stock_provider_falls_back_to_the_other_bank(setup):
    folder, subtitles, params, _, search, images, _ = setup
    search.side_effect = lambda provider, *args: [] if provider == "pexels" else [MaterialInfo(provider=provider, url="https://stock.example.test/pixabay.mp4", duration=10)]
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    scenes = json.loads((folder / "mixed-scenes.json").read_text())["scenes"]
    assert scenes[0]["provenance"]["provider"] == "pixabay"
    assert images.call_count == 1


def test_empty_stock_search_falls_back_within_budget(setup):
    _, subtitles, params, _, search, images, _ = setup
    search.return_value = []
    search.side_effect = None
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert images.call_count == 3


def test_empty_stock_search_cannot_spend_budget_reserved_for_reconstruction(setup):
    _, subtitles, params, _, search, images, _ = setup
    params.mixed_max_images = 1
    search.return_value = []
    search.side_effect = None
    with pytest.raises(mixed.MixedError, match="reserved"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    images.assert_not_called()


def test_pixabay_can_be_the_only_configured_stock_source(setup, monkeypatch):
    _, subtitles, params, _, search, _, _ = setup
    monkeypatch.delitem(mixed.config.app, "pexels_api_keys")
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert all(call.args[0] == "pixabay" for call in search.call_args_list)


@pytest.mark.parametrize("bad_plan", ["[]", "{}", "Error: unavailable", '[{"id":9}]'])
def test_invalid_scene_plan_never_orders_images(setup, bad_plan):
    _, subtitles, params, model, _, images, _ = setup
    model.return_value = bad_plan
    with pytest.raises(mixed.MixedError, match="invalid plan"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    images.assert_not_called()


def test_estimated_timing_is_explicit_and_covers_the_entire_audio():
    units, timing = mixed.timeline(SCRIPT, 31.17, "", 5)
    assert timing == "estimated"
    assert units[0]["start_frame"] == 0
    assert units[-1]["end_frame"] == 936
    assert all(a["end_frame"] == b["start_frame"] for a, b in zip(units, units[1:]))


def test_real_render_and_concat_preserve_scene_order_and_duration(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    from moviepy import VideoFileClip
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (160, 90))
    sources = []
    for i, color in enumerate(("red", "blue")):
        source = tmp_path / f"source-{i}.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s=160x90:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        target = tmp_path / f"scene-{i}.mp4"
        mixed.render(source, target, 45, VideoParams(video_subject="test", n_threads=1))
        sources.append(str(target))
    output = tmp_path / "combined.mp4"
    mixed.join(sources, str(output))
    with VideoFileClip(str(output)) as clip:
        assert abs(clip.duration - 3) < 0.05
        assert clip.get_frame(0.25)[0, 0, 0] > 200
        assert clip.get_frame(2.0)[0, 0, 2] > 200


def test_full_pipeline_mixes_real_clips_without_shuffling(tmp_path, monkeypatch):
    from moviepy import VideoFileClip
    from app.services import task as tm

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    def task_dir(task_id=""):
        path = tmp_path / "tasks" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    monkeypatch.setattr(mixed.utils, "task_dir", task_dir)
    monkeypatch.setattr(mixed.sm, "state", MemoryState())
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (160, 90))
    monkeypatch.setattr(mixed.config, "app", {"pexels_api_keys": ["test"], "pixabay_api_keys": ["test"],
                                             "openai_image_base_url": "https://images.example.test/v1", "openai_image_model": "test"})
    clips = {}
    for provider, color in (("pexels", "red"), ("openai_image", "blue"), ("pixabay", "green")):
        target = tmp_path / (provider + ".mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s=160x90:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)], check=True)
        clips[provider] = str(target)
    audio = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=6", str(audio)], check=True)
    subtitles = tmp_path / "captions.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:02,000\nHoje preparamos café.\n\n"
                         "2\n00:00:02,000 --> 00:00:04,000\nTrabalho de pessoas escravizadas.\n\n"
                         "3\n00:00:04,000 --> 00:00:06,000\nHoje embalamos os grãos.\n\n", encoding="utf-8")
    # Use one source per sentence to make the integration's visual order observable.
    real_timeline = mixed.timeline
    monkeypatch.setattr(mixed, "timeline", lambda script, duration, subtitle, desired: real_timeline(script, duration, subtitle, 1))
    choices = [{"id": i, "source": "stock", "context": "current", "period": "19th century" if i == 2 else "today",
                "location": "Brazil", "search_query": f"scene {i}", "image_prompt": "Contextual coffee illustration", "reason": "Narrative fit"}
               for i in (1, 2, 3)]
    monkeypatch.setattr(mixed.llm, "_generate_response", lambda **kwargs: json.dumps(choices))
    monkeypatch.setattr(mixed.material, "_search_videos_with_cache", lambda provider, *args: [MaterialInfo(provider=provider, url=provider, duration=1)])
    monkeypatch.setattr(mixed.material, "save_video", lambda url, directory: clips[url])
    image = tmp_path / "generated.png"
    image.write_bytes(b"simulated downloaded image")
    generate = Mock(return_value=[MaterialInfo(provider="openai_image", url=str(image), duration=1)])
    monkeypatch.setattr(mixed.material, "generate_images_openai", generate)
    monkeypatch.setattr(mixed.material, "_render_openai_image_video", lambda *args, **kwargs: clips["openai_image"])
    monkeypatch.setattr(tm, "generate_audio", lambda *args, **kwargs: (str(audio), 6, None))
    monkeypatch.setattr(tm, "generate_subtitle", lambda *args, **kwargs: str(subtitles))
    terms = Mock(side_effect=AssertionError("Mixed mode must plan from narration, not global search terms"))
    monkeypatch.setattr(tm, "generate_terms", terms)
    monkeypatch.setattr(tm.upload_post.upload_post_service, "is_configured", lambda: False)
    params = VideoParams(video_subject="Coffee", video_script=SCRIPT, video_source="mixed", mixed_visual_validation=False, subtitle_enabled=False,
                         bgm_type="", n_threads=1, video_clip_speed=2.0)
    result = tm.start("integration", params)
    assert result.get("videos"), result
    assert result["mixed_image_requests"] == 1
    with VideoFileClip(result["videos"][0]) as clip:
        assert abs(clip.duration - 6) < 0.1
        assert clip.audio is not None
        assert clip.get_frame(0.5)[0, 0, 0] > 200
        assert clip.get_frame(2.5)[0, 0, 2] > 200
        assert clip.get_frame(4.5)[0, 0, 1] > 90
    terms.assert_not_called()
    assert generate.call_count == 1


def test_historical_context_changes_can_split_scenes_before_target_duration(tmp_path):
    subtitles = tmp_path / "history.srt"
    subtitles.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\nHoje visitamos uma cafeteria moderna.\n\n"
        "2\n00:00:04,000 --> 00:00:08,000\nNo século XIX, havia trabalho escravizado.\n\n"
        "3\n00:00:08,000 --> 00:00:12,000\nHoje a produção utiliza equipamentos modernos.\n\n", encoding="utf-8")
    units, timing = mixed.timeline("", 12, str(subtitles), 10)
    assert timing == "subtitles"
    assert len(units) == 3
    assert [(unit["start_frame"], unit["end_frame"]) for unit in units] == [(0, 120), (120, 240), (240, 360)]


def test_historical_safety_route_removes_a_conflicting_present_day_period(setup):
    _, subtitles, params, model, _, images, _ = setup
    choices = json.loads(model.return_value)
    choices[1]["period"] = "present day"
    model.return_value = json.dumps(choices)
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    prompt = images.call_args.kwargs["search_term"]
    assert "Period: present day" not in prompt
    assert "Historical period described in the narration" in prompt


def test_current_century_is_not_forced_into_a_historical_reconstruction(setup):
    _, _, _, model, _, _, _ = setup
    choice = json.loads(model.return_value)[0]
    model.return_value = json.dumps([choice])
    scenes = mixed._plan([{"id": 1, "text": "No século XXI, compramos café em lojas modernas.",
                           "start_frame": 0, "end_frame": 300}], "Café atual")
    assert scenes[0]["source"] == "stock"
    assert scenes[0]["context"] == "current"


def test_budget_failure_reports_the_exact_required_limit_and_started_counts(setup):
    _, subtitles, params, _, _, images, _ = setup
    params.mixed_max_images = 0
    with pytest.raises(mixed.MixedBudgetError) as captured:
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert captured.value.key == "mixed.image_budget"
    assert captured.value.params == {"required": 1, "limit": 0, "started": 0}
    images.assert_not_called()


def test_imported_narration_requires_whisper_before_script_audio_or_scene_calls(setup, monkeypatch):
    from app.services import task as tm
    _, _, params, model, _, images, _ = setup
    params.custom_audio_file = "narration.mp3"
    params.subtitle_enabled = True
    script = Mock()
    audio = Mock()
    monkeypatch.setattr(tm, "generate_script", script)
    monkeypatch.setattr(tm, "generate_audio", audio)
    result = tm.start("external", params)
    assert result["failed_stage"] == "preflight"
    assert result["error_key"] == "mixed.external_subtitles"
    script.assert_not_called()
    audio.assert_not_called()
    model.assert_not_called()
    images.assert_not_called()


def test_budget_failure_is_a_material_failure_not_a_truthy_material_list(setup):
    from app.services import task as tm
    _, subtitles, params, _, _, images, _ = setup
    params.mixed_max_images = 0
    result = tm.get_video_materials("job", params, [], 30, mixed_script=SCRIPT, mixed_subtitle=str(subtitles))
    assert result is None
    failure = tm.sm.state.get_task("job")
    assert failure["failed_stage"] == "materials"
    assert failure["error_key"] == "mixed.image_budget"
    assert failure["error_params"]["required"] == 1
    images.assert_not_called()


def test_failed_whisper_stops_before_paid_scene_planning(setup, monkeypatch):
    from app.services import task as tm
    _, _, params, model, _, images, _ = setup
    params.custom_audio_file = "narration.mp3"
    params.subtitle_enabled = True
    monkeypatch.setitem(mixed.config.app, "subtitle_provider", "whisper")
    monkeypatch.setattr(tm, "generate_audio", lambda *args, **kwargs: ("narration.mp3", 30, None))
    monkeypatch.setattr(tm, "generate_subtitle", lambda *args, **kwargs: "")
    result = tm.start("external", params)
    assert result["failed_stage"] == "subtitle"
    assert result["error_key"] == "mixed.whisper_failed"
    model.assert_not_called()
    images.assert_not_called()


def test_neutral_sentences_do_not_split_a_continuing_historical_passage(tmp_path):
    subtitles = tmp_path / "continuous-history.srt"
    subtitles.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\nNo século XIX, o café se expandiu.\n\n"
        "2\n00:00:04,000 --> 00:00:08,000\nEssa expansão estimulou ferrovias e cidades.\n\n"
        "3\n00:00:08,000 --> 00:00:12,000\nO trabalho de pessoas escravizadas sustentava as lavouras.\n\n", encoding="utf-8")
    units, _ = mixed.timeline("", 12, str(subtitles), 20)
    assert len(units) == 1
    assert "ferrovias" in units[0]["text"]


def test_coverr_is_rotated_alongside_pexels_and_pixabay(setup, monkeypatch):
    folder, _, params, model, search, images, _ = setup
    monkeypatch.setitem(mixed.config.app, "coverr_api_keys", ["test-coverr"])
    choices = json.loads(model.return_value)
    for row in choices:
        row.update(context="current", period="today", source="image")
    model.return_value = json.dumps(choices)
    script = "Hoje torramos café. Hoje embalamos café. Hoje preparamos café."
    mixed.prepare("job", params, script, 30)
    assert [call.args[0] for call in search.call_args_list] == ["pexels", "pixabay", "coverr"]
    assert search.call_args_list[-1].args[1] is mixed.material.search_videos_coverr
    scenes = json.loads((folder / "mixed-scenes.json").read_text())["scenes"]
    assert [s["provenance"]["provider"] for s in scenes] == ["pexels", "pixabay", "coverr"]
    images.assert_not_called()
    assert mixed.sm.state.get_task("job")["mixed_source_counts"] == {
        "pexels": 1, "pixabay": 1, "coverr": 1, "openai_image": 0}


def test_coverr_can_be_the_only_configured_bank(setup, monkeypatch):
    _, subtitles, params, _, search, _, _ = setup
    monkeypatch.delitem(mixed.config.app, "pexels_api_keys")
    monkeypatch.delitem(mixed.config.app, "pixabay_api_keys")
    monkeypatch.setitem(mixed.config.app, "coverr_api_keys", "test-coverr")
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert all(call.args[0] == "coverr" for call in search.call_args_list)


def test_historical_narration_can_use_approved_timeless_stock_details(setup):
    _, subtitles, params, model, search, images, _ = setup
    choices = json.loads(model.return_value)
    choices[1].update(source="image", context="historical", stock_safe=True,
                      search_query="coffee beans close up", reason="Timeless supporting detail, no depiction of labor")
    model.return_value = json.dumps(choices)
    params.mixed_max_images = 0
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert search.call_count == 3
    images.assert_not_called()


def test_stock_search_tries_alternate_query_and_coverr_before_stopping(setup, monkeypatch):
    _, subtitles, params, model, search, images, _ = setup
    monkeypatch.setitem(mixed.config.app, "coverr_api_keys", ["test-coverr"])
    choices = json.loads(model.return_value)
    choices[0]["alternate_queries"] = ["coffee beans"]
    model.return_value = json.dumps(choices)
    search.side_effect = lambda provider, method, query, *args: (
        [MaterialInfo(provider=provider, url="https://stock.example.test/clip.mp4", duration=10)]
        if provider == "coverr" and query == "coffee beans" else [])
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert [(c.args[0], c.args[2]) for c in search.call_args_list[:6]] == [
        (p, q) for q in ["coffee scene 1", "coffee beans"] for p in ["pexels", "pixabay", "coverr"]]
    assert images.call_count == 2


def test_needed_images_are_allowed_above_soft_stock_target(setup):
    _, subtitles, params, model, search, images, _ = setup
    choices = json.loads(model.return_value)
    for row in choices:
        row.update(context="historical", source="image")
    model.return_value = json.dumps(choices)
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    search.assert_not_called()
    assert images.call_count == 3


def test_visual_rejection_tries_other_provider_then_uses_ai_within_limit(setup, monkeypatch):
    _, subtitles, params, _, search, images, _ = setup
    params.mixed_visual_validation = True
    monkeypatch.setitem(mixed.config.app, "openai_api_key", "test-key")
    inspect = Mock(return_value=(False, {"relevant": False, "confidence": 0.99, "reason": "Unrelated insects"}))
    monkeypatch.setattr(mixed.visual_validation, "inspect_clip", inspect)
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert inspect.call_count == 4  # two configured banks for each stock scene
    assert images.call_count == 3
    assert search.call_args_list[0].args[0] == "pexels"
    assert search.call_args_list[1].args[0] == "pixabay"


def test_visual_api_failure_never_approves_or_falls_back_to_paid_image(setup, monkeypatch):
    _, subtitles, params, _, _, images, _ = setup
    params.mixed_visual_validation = True
    monkeypatch.setitem(mixed.config.app, "openai_api_key", "test-key")
    monkeypatch.setattr(mixed.visual_validation, "inspect_clip", Mock(side_effect=
        mixed.visual_validation.VisualValidationError("API unavailable")))
    with pytest.raises(mixed.MixedError) as captured:
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert captured.value.key == "mixed.vision_failed"
    images.assert_not_called()


def test_visual_candidates_have_a_hard_per_scene_limit(setup, monkeypatch):
    _, _, params, model, search, _, _ = setup
    params.mixed_max_candidates = 1
    params.mixed_visual_validation = True
    scene = {**json.loads(model.return_value)[0], "text": "Hoje preparamos café.", "start_frame": 0, "end_frame": 300}
    inspect = Mock(return_value=(False, {}))
    monkeypatch.setattr(mixed.visual_validation, "inspect_clip", inspect)
    assert mixed._stock(scene, params, setup[0], ["pexels", "pixabay"], set()) == (None, None)
    assert inspect.call_count == 1


@pytest.mark.parametrize("start_time", [0, 27, 32, 177, 187])
def test_reframing_changes_at_global_boundary_without_new_media(tmp_path, monkeypatch, start_time):
    import numpy as np
    from PIL import Image
    from moviepy import VideoFileClip
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (160, 90))
    x, y = np.meshgrid(np.arange(320), np.arange(180))
    pattern = np.stack([(x % 40 < 20) * 255, (y % 40 < 20) * 255, (x % 30 < 15) * 255], axis=-1).astype("uint8")
    image = tmp_path / "approved.png"
    Image.fromarray(pattern).save(image)
    params = VideoParams(video_subject="test", mixed_variable_pacing=True, n_threads=1)
    output = tmp_path / "cuts.mp4"
    mixed.render(image, output, 180, params, start_time=start_time)
    with VideoFileClip(str(output)) as clip:
        assert abs(clip.duration - 6) < 0.05
        before = clip.get_frame(2.5).astype(float)
        earlier = clip.get_frame(1.5).astype(float)
        after = clip.get_frame(3.5).astype(float)
        assert np.abs(before - earlier).mean() < 2
        assert np.abs(after - before).mean() > 3
    params.mixed_variable_pacing = False
    output = tmp_path / "fixed.mp4"
    mixed.render(image, output, 180, params, start_time=start_time)
    with VideoFileClip(str(output)) as clip:
        assert np.abs(clip.get_frame(3.5).astype(float) - clip.get_frame(2.5).astype(float)).mean() < 2
