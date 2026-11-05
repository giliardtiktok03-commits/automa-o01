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

    def render(source, output, frames, params):
        output.write_bytes((str(source)+str(frames)).encode())
    rendering = Mock(side_effect=render)
    monkeypatch.setattr(mixed, "render", rendering)
    params = VideoParams(video_subject="Café", video_script=SCRIPT, video_source="mixed", mixed_scene_duration=5)
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


def test_stock_only_scene_falls_back_to_image_within_budget(setup):
    folder, subtitles, params, _, search, images, _ = setup
    search.side_effect = lambda provider, method, query, *args: [] if query.endswith("1") else [MaterialInfo(provider=provider, url="https://stock.example.test/clip.mp4", duration=10)]
    mixed.prepare("job", params, SCRIPT, 30, str(subtitles))
    assert images.call_count == 2
    assert json.loads((folder / "mixed-scenes.json").read_text())["scenes"][0]["provenance"]["provider"] == "openai_image"


def test_stock_fallback_does_not_consume_budget_reserved_for_historical_passage(setup):
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
    params = VideoParams(video_subject="Coffee", video_script=SCRIPT, video_source="mixed", subtitle_enabled=False,
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
