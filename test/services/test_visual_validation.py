import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import numpy as np
import pytest
from PIL import Image

from app.services import visual_validation as visual


@pytest.fixture
def inspection(tmp_path, monkeypatch):
    clip = MagicMock()
    clip.__enter__.return_value = clip
    clip.duration = 10
    clip.get_frame.return_value = np.full((90, 160, 3), 120, dtype=np.uint8)
    monkeypatch.setattr(visual, "VideoFileClip", Mock(return_value=clip))
    client = MagicMock()
    client.__enter__.return_value = client
    create = client.chat.completions.create
    create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
        "relevant": False, "confidence": 0.99, "reason": "Ants do not depict enslaved people"})))])
    constructor = Mock(return_value=client)
    monkeypatch.setattr(visual, "OpenAI", constructor)
    scene = {"text": "Pessoas escravizadas foram submetidas à perda de liberdade.", "context": "historical",
             "period": "19th century", "location": "Brazil", "start_frame": 0, "end_frame": 150}
    settings = {"openai_api_key": "never-store-this-key"}
    return tmp_path, scene, settings, clip, create, constructor


def test_frames_are_compared_to_passage_and_cached_without_credentials(inspection):
    directory, scene, settings, clip, create, constructor = inspection
    accepted, verdict = visual.inspect_clip("video.mp4", scene, directory, settings, "vision-test")
    assert not accepted
    assert "Ants" in verdict["reason"]
    kwargs = create.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert len(content) == 4
    assert scene["text"] in content[0]["text"]
    assert all(item["image_url"]["detail"] == "low" for item in content[1:])
    assert [call.args[0] for call in clip.get_frame.call_args_list] == [0.5, 2.5, 4.5]
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert visual.inspect_clip("video.mp4", scene, directory, settings, "vision-test")[0] is False
    assert create.call_count == 1
    assert "never-store-this-key" not in (directory / "visual-checks.json").read_text()
    scene["text"] = "Uma colônia de formigas trabalhando."
    visual.inspect_clip("video.mp4", scene, directory, settings, "vision-test")
    assert create.call_count == 2


@pytest.mark.parametrize("payload", ["invalid", '{"relevant":"yes","confidence":1,"reason":"x"}',
                                    '{"relevant":true,"confidence":2,"reason":"x"}'])
def test_invalid_verdict_never_approves_or_caches(inspection, payload):
    directory, scene, settings, _, create, _ = inspection
    create.return_value.choices[0].message.content = payload
    with pytest.raises(visual.VisualValidationError):
        visual.inspect_clip("video.mp4", scene, directory, settings, "vision-test")
    assert not (directory / "visual-checks.json").exists()


def test_uncertain_approval_is_rejected(inspection):
    directory, scene, settings, _, create, _ = inspection
    create.return_value.choices[0].message.content = json.dumps({"relevant": True, "confidence": 0.5, "reason": "Uncertain"})
    assert visual.inspect_clip("video.mp4", scene, directory, settings, "vision-test")[0] is False


def test_real_clip_frame_extraction_is_reduced_and_ordered(tmp_path, monkeypatch):
    import base64
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=640x360:r=10:d=1", "-c:v", "libx264", str(path)], check=True)
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content='{"relevant":true,"confidence":0.95,"reason":"Red background"}'))])
    monkeypatch.setattr(visual, "OpenAI", Mock(return_value=client))
    accepted, _ = visual.inspect_clip(path, {"text": "Red background", "start_frame": 0, "end_frame": 30},
                                      tmp_path, {"openai_api_key": "test"}, "vision-test")
    assert accepted
    content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    for item in content[1:]:
        raw = base64.b64decode(item["image_url"]["url"].split(",")[1])
        with Image.open(io.BytesIO(raw)) as frame:
            assert frame.size == (512, 288)
            assert frame.getpixel((5, 5))[0] > 200


def test_mixed_final_subtitles_preserve_rendered_pixels(tmp_path, monkeypatch):
    import shutil
    import subprocess
    from moviepy import VideoFileClip
    from app.models.schema import VideoAspect, VideoParams
    from app.services import video
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (160, 90))
    source = tmp_path / "source.mp4"
    audio = tmp_path / "voice.wav"
    subtitles = tmp_path / "captions.srt"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=160x90:r=10:d=1", "-c:v", "libx264", str(source)], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", str(audio)], check=True)
    subtitles.write_text("1\n00:00:00,000 --> 00:00:00,900\nCoffee history\n", encoding="utf-8")
    outputs = []
    for kind in ("pexels", "mixed"):
        target = tmp_path / (kind + ".mp4")
        params = VideoParams(video_subject="Coffee", video_source=kind, subtitle_enabled=True,
                             font_name="BeVietnamPro-Medium.ttf", font_size=12, stroke_width=1,
                             text_fore_color="#FFFFFF", bgm_type="", n_threads=1)
        video.generate_video(str(source), str(audio), str(subtitles), str(target), params)
        with VideoFileClip(str(target)) as clip:
            assert clip.audio is not None
            outputs.append(clip.get_frame(0.4))
    assert np.abs(outputs[0].astype(float) - outputs[1].astype(float)).mean() < 2
    assert (outputs[1][-35:, :, 0] > 180).sum() > 10  # visible subtitle on blue background
