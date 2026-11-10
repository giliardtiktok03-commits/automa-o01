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
                                             "openai_image_base_url": "https://images.example.test/v1", "openai_image_model": "test-model", "ai33_api_key": "test-ai33", "ai33_image_model": "test-model"})
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
    search = Mock(side_effect=lambda provider, *args: [MaterialInfo(provider=provider, url=f"https://stock.example.test/{provider}.mp4", duration=60)])
    monkeypatch.setattr(mixed.material, "_search_videos_with_cache", search)

    def save(url, directory):
        path = Path(directory) / (url.rsplit('/', 1)[-1])
        path.write_bytes(url.encode())
        return str(path)
    monkeypatch.setattr(mixed.material, "save_video", save)

    def image(**kwargs):
        path = Path(kwargs["save_dir"]) / (str(images.call_count) + "-generated.png")
        path.write_bytes(str(images.call_count).encode())
        return [MaterialInfo(provider="openai_image", url=str(path), duration=1)]
    images = Mock(side_effect=image)
    def ai33_generate(params, prompt, directory, *, before_submit=None):
        if before_submit:
            before_submit()
        Path(directory).mkdir(parents=True, exist_ok=True)
        items = images(search_term=prompt, minimum_duration=1, save_dir=str(directory))
        if not items:
            raise mixed.AI33Error("Image generation did not yield a usable result")
        return Path(items[0].url), {"task_id": "ai33-test-id", "model_id": "test-model"}
    monkeypatch.setattr(mixed.ai33_provider, "generate", ai33_generate)
    monkeypatch.setattr(mixed.material, "_render_openai_image_video", lambda *args, **kwargs: "image-clip.mp4")

    def render(source, output, frames, params, **kwargs):
        output.write_bytes((str(source)+str(frames)).encode())
    rendering = Mock(side_effect=render)
    monkeypatch.setattr(mixed, "render", rendering)
    params = VideoParams(video_subject="Café", video_script=SCRIPT, video_source="mixed", mixed_use_ai33=True, mixed_use_runware=False, mixed_use_grok=False, mixed_visual_validation=False, mixed_variable_pacing=False, mixed_scene_duration=5)
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
    assert [scene["provenance"]["provider"] for scene in manifest["scenes"]] == ["pexels", "ai33_image", "pixabay"]
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
    with pytest.raises(mixed.MixedError, match="no checkpoint"):
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
    search.side_effect = lambda provider, *args: [] if provider == "pexels" else [MaterialInfo(provider=provider, url="https://stock.example.test/pixabay.mp4", duration=60)]
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


@pytest.mark.parametrize("source", ["mixed", "ai33_image", "grok_image", "google_flow", "deepinfra_image"])
def test_full_pipeline_mixes_real_clips_without_shuffling(tmp_path, monkeypatch, source):
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
                                             "openai_image_base_url": "https://images.example.test/v1", "openai_image_model": "test", "ai33_api_key": "test-ai33", "ai33_image_model": "test", "grok_image_api_key": "test-grok", "deepinfra_api_key":"test-deepinfra"})
    clips = {}
    for provider, color in (("pexels", "red"), ("openai_image", "blue"), ("pixabay", "green")):
        target = tmp_path / (provider + ".mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s=160x90:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)], check=True)
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
    monkeypatch.setattr(mixed.material, "_search_videos_with_cache", lambda provider, *args: [MaterialInfo(provider=provider, url=provider, duration=3)])
    monkeypatch.setattr(mixed.material, "save_video", lambda url, directory: clips[url])
    def create_image():
        image = tmp_path / f"generated-{generate.call_count}.png"
        image.write_text(str(generate.call_count))
        return [MaterialInfo(provider="ai33_image", url=str(image), duration=1)]
    generate = Mock(side_effect=create_image)
    def generate_ai33(params, prompt, directory, *, before_submit=None):
        if before_submit:
            before_submit()
        return Path(generate()[0].url), {"task_id": "test-id"}
    monkeypatch.setattr(mixed.ai33_provider, "generate", generate_ai33)
    def generate_runware(params, prompt, directory, *, before_submit=None, existing_only=False):
        return generate_ai33(params, prompt, directory, before_submit=before_submit)
    monkeypatch.setattr(mixed.grok_image, "generate", generate_runware)
    def generate_flow(params, prompt, folder, scene_id, job_folder, *, before_submit=None):
        return generate_ai33(params, prompt, job_folder, before_submit=before_submit)
    monkeypatch.setattr(mixed.google_flow, "generate", generate_flow)
    monkeypatch.setattr(mixed.deepinfra_image, "generate", generate_runware)
    def render_image(image, *args, **kwargs):
        index = int(Path(image).read_text()) - 1
        return clips[("pexels", "openai_image", "pixabay")[index]] if source in {"ai33_image", "grok_image", "google_flow", "deepinfra_image"} else clips["openai_image"]
    monkeypatch.setattr(mixed.material, "_render_openai_image_video", render_image)
    monkeypatch.setattr(tm, "generate_audio", lambda *args, **kwargs: (str(audio), 6, None))
    monkeypatch.setattr(tm, "generate_subtitle", lambda *args, **kwargs: str(subtitles))
    terms = Mock(side_effect=AssertionError("Mixed mode must plan from narration, not global search terms"))
    monkeypatch.setattr(tm, "generate_terms", terms)
    monkeypatch.setattr(tm.upload_post.upload_post_service, "is_configured", lambda: False)
    params = VideoParams(video_subject="Coffee", video_script=SCRIPT, video_source=source, google_flow_mode="manual_import", mixed_use_ai33=True, mixed_use_runware=False, mixed_use_grok=False, mixed_visual_validation=False, mixed_variable_pacing=False, subtitle_enabled=False,
                         bgm_type="", n_threads=1, video_clip_speed=2.0)
    result = tm.start("integration", params)
    assert result.get("videos"), result
    assert result["mixed_image_requests"] == (1 if source == "mixed" else 3)
    with VideoFileClip(result["videos"][0]) as clip:
        assert abs(clip.duration - 6) < 0.1
        assert clip.audio is not None
        assert clip.get_frame(0.5)[0, 0, 0] > 200
        assert clip.get_frame(2.5)[0, 0, 2] > 200
        assert clip.get_frame(4.5)[0, 0, 1] > 90
    terms.assert_not_called()
    assert generate.call_count == (1 if source == "mixed" else 3)


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
        "pexels": 1, "pixabay": 1, "coverr": 1, "openai_image": 0, "ai33_image": 0, "runware_image": 0, "grok_image": 0, "google_flow": 0, "deepinfra_image": 0}


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
        [MaterialInfo(provider=provider, url="https://stock.example.test/clip.mp4", duration=60)]
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
    assert mixed._stock(scene, params, setup[0], ["pexels", "pixabay"], {}) == (None, None)
    assert inspect.call_count == 1



def test_variable_pacing_requires_distinct_material_units():
    units = [{"id": 1, "text": "Coffee history", "start_frame": 0, "end_frame": 6000}]
    shots = mixed.shot_timeline(units, 200, 0, 10)
    assert [s["end_frame"] - s["start_frame"] for s in shots[:10]] == [90] * 10
    assert [s["end_frame"] - s["start_frame"] for s in shots[10:40]] == [150] * 30
    assert [s["end_frame"] - s["start_frame"] for s in shots[40:]] == [300] * 2
    assert shots[-1]["end_frame"] == 6000


def test_variable_pacing_uses_global_chapter_clock():
    units = [{"id": 1, "text": "Coffee history", "start_frame": 0, "end_frame": 300}]
    shots = mixed.shot_timeline(units, 10, 177, 10)
    assert [(s["start_frame"], s["end_frame"]) for s in shots] == [(0, 90), (90, 300)]


@pytest.mark.parametrize("position,allowed", [(59, False), (60, True)])
def test_stock_reuse_only_after_sixty_percent_and_from_unused_segment(setup, position, allowed):
    folder, _, params, model, _, _, _ = setup
    params.mixed_total_duration = 100
    scene = {**json.loads(model.return_value)[0], "text": "Coffee", "start_frame": position * 30, "end_frame": (position + 3) * 30}
    # The same ID is blocked regardless of the download URL.
    def first_record():
        return mixed._stock(scene, params, folder, ["pexels"], {})
    _, record = first_record()
    used = {record["source_digest"]: 3, record["source_identity"]: 3}
    path, again = mixed._stock(scene, params, folder, ["pexels"], used)
    assert bool(path) is allowed
    if allowed:
        assert again["source_start"] == 3 and again["source_end"] == 6


def test_unclassified_ai33_error_stops_without_editorial_card_or_paid_retry(setup):
    folder, subtitles, params, _, _, images, _ = setup
    images.side_effect = mixed.AI33Error("unclassified remote failure")
    with pytest.raises(mixed.MixedError, match="unclassified"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert not list((folder / "mixed").glob("card-*.png"))
    with pytest.raises(mixed.MixedError, match="no checkpoint"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert images.call_count == 1


def test_technical_image_failure_does_not_silently_become_editorial_card(setup):
    folder, subtitles, params, _, _, images, _ = setup
    images.return_value = []
    images.side_effect = None
    with pytest.raises(mixed.MixedError, match="usable result"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert not list((folder / "mixed").glob("card-*.png"))


def test_three_candidates_are_distributed_across_three_configured_banks(setup, monkeypatch):
    folder, _, params, model, search, _, _ = setup
    params.mixed_visual_validation = True
    monkeypatch.setitem(mixed.config.app, "coverr_api_keys", ["test-coverr"])
    inspect = Mock(side_effect=[(False, {}), (False, {}), (True, {})])
    monkeypatch.setattr(mixed.visual_validation, "inspect_clip", inspect)
    search.side_effect = lambda provider, *args: [
        MaterialInfo(provider=provider, url=f"https://stock.example.test/{provider}-{i}.mp4", duration=60)
        for i in range(5)]
    scene = {**json.loads(model.return_value)[0], "text": "Coffee", "start_frame": 0, "end_frame": 90}
    path, provenance = mixed._stock(scene, params, folder, ["pexels", "pixabay", "coverr"], {})
    assert path and provenance["provider"] == "coverr"
    assert [c.args[0] for c in search.call_args_list] == ["pexels", "pixabay", "coverr"]
    assert inspect.call_count == 3


def test_local_editorial_card_renders_without_image_api(tmp_path, monkeypatch):
    from moviepy import VideoFileClip
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (640, 360))
    params = VideoParams(video_subject="Context", video_language="en", n_threads=1)
    scene = {"id": 2, "period": "2018", "location": "The Hague", "text": "Electronic equipment was found in a rental car."}
    image = mixed._context_card(scene, params, tmp_path)
    target = tmp_path / "card.mp4"
    mixed.render(image, target, 30, params)
    with VideoFileClip(str(target)) as clip:
        assert abs(clip.duration - 1) < 0.05
        frame = clip.get_frame(0.5)
        assert frame.max() > 200
        assert frame.mean() > 20


@pytest.mark.parametrize("legacy_provider", ["flow_browser", "openai", "openai_flow"])
def test_legacy_provider_selection_routes_new_images_only_to_ai33(setup, monkeypatch, legacy_provider):
    folder, subtitles, params, _, _, images, _ = setup
    params.mixed_image_provider = legacy_provider
    flow = Mock(side_effect=AssertionError("Flow must never generate"))
    openai = Mock(side_effect=AssertionError("OpenAI Image must never generate"))
    monkeypatch.setattr(mixed.flow_browser, "generate", flow)
    monkeypatch.setattr(mixed.material, "generate_images_openai", openai)
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert params.mixed_image_provider == "ai33"
    assert images.call_count == 1
    flow.assert_not_called()
    openai.assert_not_called()
    assert mixed.sm.state.get_task("job")["mixed_source_counts"]["ai33_image"] == 1


def test_sources_start_enabled_and_disabled_bank_is_never_searched(setup):
    _, subtitles, params, _, search, _, _ = setup
    assert all(getattr(params, 'mixed_use_'+name) for name in ('pexels','pixabay','coverr','ai33'))
    params.mixed_use_pexels=False
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert all(call.args[0]=='pixabay' for call in search.call_args_list)


def test_selecting_ai33_only_skips_all_banks(setup):
    _, subtitles, params, _, search, images, _ = setup
    params.mixed_select_sources = True
    params.mixed_use_pexels = params.mixed_use_pixabay = params.mixed_use_coverr = False
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert images.call_count == 3 and params.mixed_image_provider == "ai33"
    search.assert_not_called()


def test_disabled_image_generators_are_not_called(setup, monkeypatch):
    _, subtitles, params, _, _, images, _ = setup
    params.mixed_select_sources=True
    params.mixed_use_ai33=False
    generate=Mock()
    monkeypatch.setattr(mixed.flow_browser,'generate',generate)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert params.mixed_image_provider=='none'
    images.assert_not_called()
    generate.assert_not_called()


def test_saved_project_resumes_after_limit_without_script_audio_or_paid_repetition(setup,monkeypatch):
    from app.services import mixed_resume, task
    import hashlib
    folder, _, params, model, search, images, rendering = setup
    task_id='5c8b2e2a-3360-449a-a84d-297f6ab90bcf'
    directory=Path(mixed.utils.task_dir(task_id))
    content=b'original external narration'
    audio=directory/f'custom-audio-{hashlib.sha256(content).hexdigest()}.mp3'
    audio.write_bytes(content)
    params.custom_audio_file=str(audio)
    params.subtitle_enabled=False
    params.mixed_max_images=1
    original_search=search.side_effect
    search.side_effect=lambda provider,method,query,*args: [] if query.endswith('3') else original_search(provider,method,query,*args)
    task.save_script_data(task_id,SCRIPT,[],params)
    with pytest.raises(mixed.MixedError,match='limit reached'):
        mixed.prepare(task_id,params,SCRIPT,30)
    assert images.call_count==1
    monkeypatch.setattr(mixed_resume.voice,'get_audio_duration',lambda *_:30)
    saved=mixed_resume.load(task_id,24)
    assert saved['ready']==2 and saved['started']==1
    model.reset_mock()
    rendering.reset_mock()
    def render_final(*args,**kwargs):
        target=directory/'final-1.mp4'
        target.write_bytes(b'final video')
        return [str(target)],[],[]
    monkeypatch.setattr(task,'generate_final_videos',render_final)
    spies=[Mock() for _ in range(3)]
    for name,spy in zip(('generate_script','generate_audio','generate_subtitle'),spies):
        monkeypatch.setattr(task,name,spy)
    monkeypatch.setattr(mixed.config, "ui", {"image_source_policy": "grok-v1", "mixed_use_ai33": True, "mixed_use_runware": False, "mixed_use_grok": False})
    result=task.start(task_id,saved['params'])
    assert result['videos'] and result['mixed_image_requests']==2
    assert images.call_count==2 and rendering.call_count==1
    model.assert_not_called()
    for spy in spies:
        spy.assert_not_called()
    assert list((directory/'resume-backups').glob('*/mixed-scenes.json'))
    assert json.loads((directory/'script.json').read_text())['params']['mixed_max_images']==24


def test_legacy_checkpoint_migrates_only_when_original_inputs_match(setup):
    import hashlib
    folder,subtitles,params,model,_,images,_=setup
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    file=folder/'mixed-scenes.json'
    saved=json.loads(file.read_text())
    signature=saved.pop('signature')
    for key in ('selected_sources',):
        signature.pop(key,None)
    saved['fingerprint']=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    file.write_text(json.dumps(saved))
    params.mixed_resume=True
    params.mixed_max_images=24
    model.reset_mock()
    images.reset_mock()
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    model.assert_not_called()
    images.assert_not_called()
    params.video_aspect='1:1'
    with pytest.raises(mixed.MixedError,match='restore the original settings'):
        mixed.prepare('job',params,SCRIPT,30,str(subtitles))


def test_legacy_provider_migration_reuses_paid_file_and_records_original_signature(setup):
    import hashlib
    folder, subtitles, params, model, _, images, _ = setup
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    path = folder / "mixed-scenes.json"
    manifest = json.loads(path.read_text())
    original = dict(manifest["signature"])
    original.update(image_provider="flow_browser", image_model="legacy-model", image_size="legacy-size", image_template="legacy")
    original.pop("image_quality", None)
    original.pop("image_credit_cap", None)
    original["selected_sources"] = {"pexels": True, "pixabay": True, "coverr": True, "openai": True, "flow": True}
    manifest["signature"] = original
    manifest["fingerprint"] = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
    scene = manifest["scenes"][1]
    scene.pop("image_provider", None)
    image = folder / "mixed" / scene["image_file"]
    before = image.read_bytes()
    path.write_text(json.dumps(manifest))
    params.mixed_resume = True
    images.reset_mock()
    model.reset_mock()
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    updated = json.loads(path.read_text())
    assert updated["original_signature"] == original
    assert updated["continuation_image_provider"] == "ai33_image"
    assert updated["scenes"][1]["image_provider"] == "flow_browser"
    assert image.read_bytes() == before
    images.assert_not_called()
    model.assert_not_called()


def test_quote_failure_before_submission_does_not_consume_request_limit(setup, monkeypatch):
    folder, subtitles, params, _, _, images, _ = setup
    generate = Mock(side_effect=mixed.AI33Error("quote exceeds cap"))
    monkeypatch.setattr(mixed.ai33_provider, "generate", generate)
    with pytest.raises(mixed.MixedError, match="quote exceeds cap"):
        mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    saved = json.loads((folder / "mixed-scenes.json").read_text())
    assert saved["image_requests"] == 0
    assert not saved["scenes"][1].get("image_request_started")
    images.assert_not_called()


def test_grok_generates_only_missing_stock_scene_and_reuses_cache(setup, monkeypatch):
    folder, subtitles, params, model, search, images, rendering = setup
    params.mixed_use_ai33 = False
    params.mixed_use_grok = True
    mixed.config.app['grok_image_api_key'] = 'private-grok-key'
    stock_search = search.side_effect
    search.side_effect = lambda provider, method, query, *args: [] if query.endswith('2') else stock_search(provider, method, query, *args)
    paid = Mock()
    def generate(params, prompt, directory, *, before_submit=None, existing_only=False):
        assert not existing_only
        before_submit()
        output = Path(directory) / 'image.png'
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(b'new grok image')
        paid()
        return output, {'task_id': 'test-grok-task', 'cost_usd': 0.001}
    monkeypatch.setattr(mixed.grok_image, 'generate', generate)
    mixed.prepare('job', params, SCRIPT, 30, str(subtitles))
    manifest = json.loads((folder / 'mixed-scenes.json').read_text())
    assert [s['provenance']['provider'] for s in manifest['scenes'][:2]] == ['pexels', 'grok_image']
    assert manifest['scenes'][2]['provenance']['provider'] in {'pexels', 'pixabay', 'coverr'}
    assert manifest['image_requests'] == 1
    images.assert_not_called()  # AI33 adapter was not invoked.
    mixed.prepare('job', params, SCRIPT, 30, str(subtitles))
    paid.assert_called_once()


def test_paid_ai33_pending_is_recovered_while_unchecked_then_new_images_use_grok(setup, monkeypatch):
    folder, subtitles, params, model, search, images, rendering = setup
    remote_id = '30258ee8-cfc0-4485-b1bc-2f9ba34bdc07'
    def pending(params, prompt, directory, *, before_submit=None):
        Path(directory).mkdir(exist_ok=True)
        (Path(directory) / 'ai33-image.json').write_text(json.dumps({'task_id': remote_id}))
        before_submit()
        raise mixed.AI33PendingError(remote_id)
    monkeypatch.setattr(mixed.ai33_provider, 'generate', pending)
    with pytest.raises(mixed.MixedPending):
        mixed.prepare('job', params, SCRIPT, 30, str(subtitles))
    params.mixed_resume = True
    params.mixed_use_ai33 = False
    params.mixed_use_grok = True
    mixed.config.app['grok_image_api_key'] = 'test-key'
    mixed.config.app['ai33_image_model'] = 'different-current-model'
    def recover(params, prompt, directory, *, before_submit=None, existing_only=False):
        assert existing_only and params.ai33_model == 'test-model'
        image = Path(directory) / 'image.png'
        image.write_bytes(b'previously paid AI33 image')
        return image, {'task_id': remote_id}
    recovery = Mock(side_effect=recover)
    monkeypatch.setattr(mixed.ai33_provider, 'generate', recovery)
    new_paid = Mock(side_effect=AssertionError('No new image should be ordered'))
    monkeypatch.setattr(mixed.grok_image, 'generate', new_paid)
    mixed.prepare('job', params, SCRIPT, 30, str(subtitles))
    manifest = json.loads((folder / 'mixed-scenes.json').read_text())
    assert manifest['image_requests'] == 1
    assert manifest['signature']['image_provider'] == 'grok'
    assert manifest['scenes'][1]['image_provider'] == 'ai33_image'
    recovery.assert_called_once()
    new_paid.assert_not_called()



def test_grok_refusal_creates_identified_card_without_second_request(setup, monkeypatch):
    folder, subtitles, params, _, _, images, _=setup
    params.mixed_use_ai33=False
    params.mixed_use_grok=True
    mixed.config.app['grok_image_api_key']='test-key'
    stock_search = mixed.material._search_videos_with_cache.side_effect
    mixed.material._search_videos_with_cache.side_effect = lambda provider, method, query, *args: [] if query.endswith('2') else stock_search(provider, method, query, *args)
    def refusal(params,prompt,directory,*,before_submit=None,existing_only=False):
        before_submit()
        raise mixed.grok_image.GrokRefusal('Provider refusal')
    paid=Mock(side_effect=refusal)
    monkeypatch.setattr(mixed.grok_image,'generate',paid)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    paid.assert_called_once()
    manifest=json.loads((folder/'mixed-scenes.json').read_text())
    assert manifest['image_requests']==1
    assert manifest['scenes'][1]['provenance']['provider']=='editorial_card'
    assert manifest['scenes'][1]['image_refused']
    assert (folder/'mixed'/'card-002.png').is_file()
    images.assert_not_called()


def test_unlimited_grok_exceeds_old_cap_and_searches_all_banks_first(setup,monkeypatch):
    folder, subtitles, params, model, search, images, _=setup
    params.mixed_use_ai33=False
    params.mixed_use_grok=True
    params.mixed_use_coverr=True
    params.mixed_max_images=0
    params.mixed_grok_unlimited=True
    mixed.config.app.update(grok_image_api_key='test-key',coverr_api_keys=['test-coverr'])
    search.side_effect=lambda *args: []
    calls=[]
    def generate(params,prompt,directory,*,before_submit=None,existing_only=False):
        assert not existing_only
        # All three sources were considered for this scene before ordering.
        assert {c.args[0] for c in search.call_args_list[-3:]}=={'pexels','pixabay','coverr'}
        before_submit()
        out=Path(directory)/'image.png'
        out.parent.mkdir(exist_ok=True)
        calls.append(prompt)
        out.write_bytes(f'new image {len(calls)}'.encode())
        return out,{'request_id':str(len(calls))}
    monkeypatch.setattr(mixed.grok_image,'generate',generate)
    # Seed a checkpoint as if the old cap was reached, preserving the same plan.
    params.mixed_grok_unlimited=False
    with pytest.raises(mixed.MixedBudgetError):
        mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    file=folder/'mixed-scenes.json'
    state=json.loads(file.read_text())
    state['image_requests']=130
    file.write_text(json.dumps(state))
    params.mixed_grok_unlimited=True
    params.mixed_resume=True
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert len(calls)==3
    assert json.loads(file.read_text())['image_requests']==133
    assert search.call_count==9
    images.assert_not_called()
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert len(calls)==3  # Saved images/scenes do not trigger extra orders.


def test_unlimited_grok_still_uses_approved_stock_for_planned_image_scene(setup,monkeypatch):
    folder, subtitles, params, _, search, images, _=setup
    params.mixed_use_ai33=False
    params.mixed_use_grok=True
    params.mixed_max_images=0
    mixed.config.app['grok_image_api_key']='test-key'
    paid=Mock(side_effect=AssertionError('Stock should be preferred'))
    monkeypatch.setattr(mixed.grok_image,'generate',paid)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    state=json.loads((folder/'mixed-scenes.json').read_text())
    assert state['image_requests']==0
    assert all(s['provenance']['provider'] in {'pexels','pixabay','coverr'} for s in state['scenes'])
    paid.assert_not_called()
    images.assert_not_called()


def test_finite_grok_mode_still_enforces_explicit_cap(setup):
    _, subtitles, params, _, _, _, _=setup
    params.mixed_use_ai33=False
    params.mixed_use_grok=True
    params.mixed_grok_unlimited=False
    params.mixed_max_images=0
    with pytest.raises(mixed.MixedBudgetError):
        mixed.prepare('job',params,SCRIPT,30,str(subtitles))


def test_flow_waits_then_imports_and_resumes_without_paid_fallback(setup,monkeypatch):
    import io
    from PIL import Image
    from uuid import uuid4
    from app.services import google_flow
    _,subtitles,params,model,search,images,_=setup
    task_id=str(uuid4())
    folder=Path(mixed.utils.task_dir(task_id))
    params.mixed_use_google_flow=True
    params.google_flow_mode='manual_import'
    params.mixed_select_sources=True
    params.mixed_max_images=0
    original=search.side_effect
    search.side_effect=lambda provider,method,query,*args:[] if query.endswith('2') else original(provider,method,query,*args)
    grok=Mock(side_effect=AssertionError('No paid Grok fallback'))
    monkeypatch.setattr(mixed.grok_image,'generate',grok)
    with pytest.raises(mixed.MixedPending) as pending:
        mixed.prepare(task_id,params,SCRIPT,30,str(subtitles))
    assert pending.value.provider=='google_flow'
    state=json.loads((folder/'mixed-scenes.json').read_text())
    assert state['image_requests']==0 and state['scenes'][0].get('sha256')
    out=io.BytesIO()
    Image.new('RGB',(320,180),'blue').save(out,format='PNG')
    google_flow.import_image(task_id,2,out.getvalue())
    params.mixed_resume=True
    result=mixed.prepare(task_id,params,SCRIPT,30,str(subtitles))
    assert len(result)==3
    state=json.loads((folder/'mixed-scenes.json').read_text())
    assert state['scenes'][1]['provenance']['provider']=='google_flow'
    assert state['image_requests']==0
    model.assert_called_once()
    images.assert_not_called()
    grok.assert_not_called()


def test_deepinfra_keeps_stock_first_and_audits_image_budget(setup, monkeypatch):
    folder, subtitles, params, _, search, _, _ = setup
    params.mixed_use_deepinfra = True
    params.mixed_select_sources = True
    mixed.config.app['deepinfra_api_key'] = 'test-key'
    search.side_effect = lambda *args, **kwargs: []
    def generate(params,prompt,directory,*,before_submit=None,**kwargs):
        assert search.called
        before_submit()
        Path(directory).mkdir(parents=True,exist_ok=True)
        image=Path(directory)/'image.png'
        image.write_bytes(('deepinfra-test:'+prompt).encode())
        return image, {'model':'stabilityai/sdxl-turbo'}
    provider=Mock(side_effect=generate)
    monkeypatch.setattr(mixed.deepinfra_image,'generate',provider)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    manifest=json.loads((folder/'mixed-scenes.json').read_text())
    assert manifest['signature']['image_provider']=='deepinfra'
    assert provider.called and manifest['image_requests']==provider.call_count
    assert any(scene.get('image_provider')=='deepinfra_image' for scene in manifest['scenes'])
    # Completed scenes are reused without another provider request.
    count=provider.call_count
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert provider.call_count==count


def test_archives_are_tried_before_stock_and_credits_only_after_render(setup,monkeypatch):
    folder,subtitles,params,_,search,_,_=setup
    from app.services.historical_archive import settings
    monkeypatch.setattr(settings,'mapping',lambda:{'historical_archive_enabled':True})
    service=Mock();service.active.return_value=True
    service.settings.return_value=__import__('app.services.historical_archive.contracts',fromlist=['ArchiveSettings']).ArchiveSettings(enabled=True)
    archive=folder/'archival.mp4';archive.write_bytes(b'archival-video')
    def choose(scene,terms):
        if scene['id']==1:return str(archive),{'provider':'historical_archive','source_identity':'archive:1','source_digest':'archive:1','source_end':1,'illustration':False}
        return None,None
    service.select.side_effect=choose
    monkeypatch.setattr(mixed,'HistoricalArchiveService',lambda *a:service)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    manifest=json.loads((folder/'mixed-scenes.json').read_text())
    assert manifest['scenes'][0]['provenance']['provider']=='historical_archive'
    assert all(call.args[2]!='coffee scene 1' for call in search.call_args_list)
    assert service.mark_used.call_count==3


def test_archive_without_cleared_assets_uses_stock_then_ai_without_approval(setup,monkeypatch):
    folder,subtitles,params,_,search,_,_=setup
    from app.services.historical_archive import settings
    monkeypatch.setattr(settings,'mapping',lambda:{'historical_archive_enabled':True})
    params.mixed_select_sources=True
    params.mixed_use_deepinfra=True
    mixed.config.app['deepinfra_api_key']='test-key'
    events=[]
    service=Mock();service.active.return_value=True
    service.select.side_effect=lambda *args:(events.append('archive') or (None,None))
    monkeypatch.setattr(mixed,'HistoricalArchiveService',lambda *args:service)
    search.side_effect=lambda *args:(events.append('stock') or [])
    def generate(params,prompt,directory,*,before_submit=None,**kwargs):
        events.append('ai')
        assert 'restricted-reference-image' not in prompt
        before_submit()
        Path(directory).mkdir(parents=True,exist_ok=True)
        target=Path(directory)/'image.png';target.write_bytes(prompt.encode())
        return target,{'model':'stabilityai/sdxl-turbo'}
    provider=Mock(side_effect=generate)
    monkeypatch.setattr(mixed.deepinfra_image,'generate',provider)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert events[0]=='archive' and events.index('stock')<events.index('ai')
    data=json.loads((folder/'mixed-scenes.json').read_text())
    assert data['image_requests']==provider.call_count
    assert all(scene['provenance']['illustration'] for scene in data['scenes'])
    assert all(scene['provenance']['authenticity']=='illustrative_reconstruction' for scene in data['scenes'])


def test_archive_failure_still_uses_configured_stock_for_image_planned_scene(setup,monkeypatch):
    folder,subtitles,params,model,search,images,_=setup
    from app.services.historical_archive import settings
    monkeypatch.setattr(settings,'mapping',lambda:{'historical_archive_enabled':True})
    params.mixed_select_sources=False
    params.mixed_image_provider='none'
    choices=json.loads(model.return_value)
    for row in choices:row.update(source='image',context='current',period='today')
    model.return_value=json.dumps(choices)
    service=Mock();service.active.return_value=True;service.select.return_value=(None,None)
    monkeypatch.setattr(mixed,'HistoricalArchiveService',lambda *args:service)
    mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert search.called
    images.assert_not_called()
    data=json.loads((folder/'mixed-scenes.json').read_text())
    assert all(s['provenance']['provider'] in {'pexels','pixabay','coverr'} for s in data['scenes'])


def test_archive_no_material_failure_explains_reason_and_disabled_fallback(setup,monkeypatch):
    folder,subtitles,params,_,_,_,_=setup
    from app.services.historical_archive import settings
    monkeypatch.setattr(settings,'mapping',lambda:{'historical_archive_enabled':True})
    params.mixed_use_pexels=params.mixed_use_pixabay=params.mixed_use_coverr=False
    params.mixed_use_ai33=params.mixed_use_grok=params.mixed_use_deepinfra=False
    params.mixed_image_provider='none'
    service=Mock();service.active.return_value=True;service.select.return_value=(None,None)
    service.explain.return_value='LOC HTTP 200; zero candidatos com direitos claros'
    monkeypatch.setattr(mixed,'HistoricalArchiveService',lambda *args:service)
    with pytest.raises(mixed.MixedError,match='zero candidatos com direitos claros') as exc:
        mixed.prepare('job',params,SCRIPT,30,str(subtitles))
    assert 'gerador de imagens selecionado: nenhum' in str(exc.value)
    assert 'diagnostic-report.json' in str(exc.value)
