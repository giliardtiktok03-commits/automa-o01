import io
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import bgm, narration


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 1600)
    return stream.getvalue()


def test_upload_limits_are_500_mib_narration_and_200_mib_bgm():
    assert narration.MAX_NARRATION_UPLOAD_BYTES == 500 * 1024 * 1024
    assert bgm.MAX_BGM_UPLOAD_BYTES == 200 * 1024 * 1024


def test_metadata_over_limit_is_rejected_before_reading(tmp_path):
    source = Mock(size=narration.MAX_NARRATION_UPLOAD_BYTES + 1)
    with pytest.raises(bgm.BgmUploadError, match="500 MB"):
        narration.save_upload("voice.wav", source, tmp_path)
    source.read.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_stream_size_is_checked_even_if_metadata_lies(tmp_path, monkeypatch):
    source = io.BytesIO(b"a" * 64)
    source.size = 1
    monkeypatch.setattr(narration, "MAX_NARRATION_UPLOAD_BYTES", 32)
    with pytest.raises(bgm.BgmUploadError, match="500 MB"):
        narration.save_upload("voice.wav", source, tmp_path)
    assert not list(tmp_path.iterdir())
    assert source.tell() == 0


def test_exact_limit_is_accepted_and_stream_position_restored(tmp_path, monkeypatch):
    content = wav_bytes()
    monkeypatch.setattr(narration, "MAX_NARRATION_UPLOAD_BYTES", len(content))
    source = io.BytesIO(content)
    source.seek(10)
    file = narration.save_upload("voice.WAV", source, tmp_path)
    assert source.tell() == 10
    assert Path(file).read_bytes() == content
    assert Path(file).parent == tmp_path
    # Uploading identical audio uses the same name; no random path breaks resume.
    assert narration.save_upload("voice.wav", source, tmp_path) == file
    assert list(tmp_path.iterdir()) == [Path(file)]


@pytest.mark.parametrize("content", [b"", b"not an audio file"])
def test_empty_or_corrupt_audio_leaves_no_partial_files(tmp_path, content):
    with pytest.raises(bgm.BgmUploadError):
        narration.save_upload("voice.wav", io.BytesIO(content), tmp_path)
    assert not list(tmp_path.iterdir())


def test_publish_failure_keeps_existing_recording_and_cleans_stage(tmp_path, monkeypatch):
    file = Path(narration.save_upload("voice.wav", io.BytesIO(wav_bytes()), tmp_path))
    original = file.read_bytes()
    monkeypatch.setattr(narration.os, "replace", Mock(side_effect=OSError("disk unavailable")))
    with pytest.raises(OSError, match="disk unavailable"):
        narration.save_upload("voice.wav", io.BytesIO(original), tmp_path)
    assert file.read_bytes() == original
    assert list(tmp_path.iterdir()) == [file]


def test_long_audio_has_a_separate_validation_timeout(tmp_path, monkeypatch):
    validate = Mock()
    monkeypatch.setattr(bgm, "validate_audio_file", validate)
    narration.save_upload("voice.wav", io.BytesIO(wav_bytes()), tmp_path)
    assert validate.call_args.kwargs["timeout_seconds"] == 600


def test_large_real_wav_is_copied_in_chunks_and_fully_decoded(tmp_path):
    original = tmp_path / "large.wav"
    with wave.open(str(original), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for _ in range(31):
            audio.writeframesraw(b"\0" * (1024 * 1024))
    destination = tmp_path / "task"
    destination.mkdir()

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream
            self.size = original.stat().st_size
            self.max_read = 0

        def read(self, count):
            assert 0 < count <= narration.COPY_CHUNK_BYTES
            self.max_read = max(self.max_read, count)
            return self.stream.read(count)

        def tell(self):
            return self.stream.tell()

        def seek(self, offset):
            return self.stream.seek(offset)

    with original.open("rb") as stream:
        reader = BoundedReader(stream)
        file = Path(narration.save_upload("large.wav", reader, destination))
        assert reader.max_read == 1024 * 1024
        assert stream.tell() == 0
    assert file.stat().st_size == original.stat().st_size > 30 * 1024 * 1024
    assert list(destination.iterdir()) == [file]
    # A recording above the former 30 MB limit is now valid background music.
    with original.open("rb") as stream:
        assert bgm.validate_bgm_upload("large.wav", stream) == "large.wav"


def test_nonseekable_source_reports_upload_error(tmp_path):
    with pytest.raises(bgm.BgmUploadError, match="seekable"):
        narration.save_upload("voice.wav", object(), tmp_path)
    assert not list(tmp_path.iterdir())
