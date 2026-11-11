"""Discover saved single-video projects. Read metadata only until enrollment/run."""
import hashlib
import json
from pathlib import Path, PureWindowsPath
from uuid import UUID

from app.models.schema import VideoParams
from app.utils import utils

SUPPORTED = {"mixed", "deepinfra_image", "grok_image", "ai33_image"}
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


class RecoveryBlocked(ValueError):
    pass


def project_dir(task_id, root=None):
    task_id = str(UUID(str(task_id)))
    root = Path(root) if root is not None else Path(utils.task_dir())
    path = root / task_id
    if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(root.resolve()):
        raise RecoveryBlocked("Projeto ausente ou fora da pasta de tarefas")
    return path


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise RecoveryBlocked("Manifesto ausente, muito grande ou inválido")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        raise RecoveryBlocked("Não foi possível ler o manifesto do projeto") from None
    if not isinstance(value, dict):
        raise RecoveryBlocked("Manifesto inválido")
    return value


def inspect(task_id, *, root=None, verify_media=False):
    folder = project_dir(task_id, root)
    saved = read_json(folder / "script.json")
    try:
        params = VideoParams.model_validate(saved["params"])
    except (ValueError, KeyError):
        raise RecoveryBlocked("Configuração salva inválida") from None
    if params.long_form or params.mixed_is_chapter:
        raise RecoveryBlocked("A recuperação de capítulos será integrada em outra entrega")
    if params.video_source not in SUPPORTED or (params.mixed_use_google_flow and not params.mixed_use_deepinfra):
        raise RecoveryBlocked("Este provedor não é suportado na recuperação AUTOPILOT")
    if (folder / "mixed").is_symlink():
        raise RecoveryBlocked("A pasta de materiais não pode ser um link simbólico")
    manifest = read_json(folder / "mixed-scenes.json")
    scenes = manifest.get("scenes", [])
    if not isinstance(scenes, list) or not scenes or len(scenes) > 720 or any(not isinstance(s, dict) or s.get("id") != i for i, s in enumerate(scenes, 1)):
        raise RecoveryBlocked("Plano de cenas inválido")
    editorial = {"script": saved.get("script"), "title": params.video_subject,
                 "voice": params.voice_name, "voice_rate": params.voice_rate,
                 "audio": params.custom_audio_file, "subtitles": params.subtitle_enabled}
    if verify_media:
        audio_name = PureWindowsPath(params.custom_audio_file).name if params.custom_audio_file else "audio.mp3"
        media = {}
        for name in [audio_name, *(["subtitle.srt"] if params.subtitle_enabled else [])]:
            file = folder / name
            if file.is_symlink() or not file.is_file() or file.stat().st_size <= 0 or file.stat().st_size > 500 * 1024 * 1024:
                raise RecoveryBlocked("Áudio ou legenda salvo ausente ou inválido")
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            media[name] = digest.hexdigest()
        editorial["media"] = media
    editorial_digest = hashlib.sha256(json.dumps(editorial, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"task_id": str(UUID(str(task_id))), "editorial_digest": editorial_digest, "title": params.video_subject,
            "registered": sum(bool(s.get("sha256") and s.get("provenance")) for s in scenes),
            "total": len(scenes), "requests": manifest.get("image_requests", 0),
            "has_output": (folder / "final-1.mp4").exists(),
            "params": params}


def discover(*, root=None, limit=2000):
    root = Path(root) if root is not None else Path(utils.task_dir())
    found = []
    # No recursion or video downloads/hashing just to open a panel.
    for folder in sorted(root.iterdir())[:limit] if root.is_dir() else []:
        try:
            UUID(folder.name)
            item = inspect(folder.name, root=root)
        except (ValueError, OSError):
            continue
        found.append({key: value for key, value in item.items() if key != "params"})
    return found
