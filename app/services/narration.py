"""Independent, bounded upload storage for large external voiceovers."""

import hashlib
import os
import tempfile
from pathlib import Path

from app.services import bgm

MAX_NARRATION_UPLOAD_MB = 500
MAX_NARRATION_UPLOAD_BYTES = MAX_NARRATION_UPLOAD_MB * 1024 * 1024
NARRATION_VALIDATION_TIMEOUT_SECONDS = 600
COPY_CHUNK_BYTES = 1024 * 1024
SUPPORTED_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"})


def save_upload(filename, source, directory):
    """Copy in bounded chunks, fully decode, then atomically publish by content hash.

    Streamlit buffers the original upload; avoid a second full in-memory copy here.
    Background music intentionally retains its own smaller limit.
    """
    safe_name = bgm.sanitize_upload_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise bgm.BgmUploadError("unsupported narration audio format")
    size = getattr(source, "size", None)
    if isinstance(size, int) and size > MAX_NARRATION_UPLOAD_BYTES:
        raise bgm.BgmUploadError("narration file exceeds the 500 MB limit")
    temporary = None
    try:
        position = source.tell()
        source.seek(0)
    except (AttributeError, OSError) as exc:
        raise bgm.BgmUploadError("narration upload must be seekable") from exc
    try:
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".narration-", suffix=extension)
        total = 0
        checksum = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output:
            while True:
                chunk = source.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise bgm.BgmUploadError("narration upload must be binary")
                total += len(chunk)
                if total > MAX_NARRATION_UPLOAD_BYTES:
                    raise bgm.BgmUploadError("narration file exceeds the 500 MB limit")
                checksum.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not total:
            raise bgm.BgmUploadError("narration file is empty")
        bgm.validate_audio_file(temporary, timeout_seconds=NARRATION_VALIDATION_TIMEOUT_SECONDS)
        destination = Path(directory) / f"custom-audio-{checksum.hexdigest()}{extension}"
        os.replace(temporary, destination)
        return str(destination)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
        source.seek(position)
