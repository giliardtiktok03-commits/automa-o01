"""Local SKILL.md library. Files are editorial data, never executable code."""

import hashlib
from pathlib import Path
import re
from uuid import uuid4

from filelock import FileLock
import yaml

from app.models.channel_skill import ChannelSkillSnapshot
from app.utils.atomic_files import write_bytes_atomic as _atomic
from app.utils import utils

MAX_FILE_BYTES = 24000


class ChannelSkillError(ValueError):
    pass


def _root():
    return Path(utils.storage_dir("channel-skills", create=True)).resolve()


def _directory(skill_id):
    if not isinstance(skill_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", skill_id):
        raise ChannelSkillError("Use um identificador com letras minúsculas, números, hífen ou sublinhado (até 48 caracteres)")
    if skill_id in {"con", "prn", "aux", "nul"} or re.fullmatch(r"(?:com|lpt)[1-9]", skill_id):
        raise ChannelSkillError("Esse identificador é reservado pelo Windows")
    directory = _root() / skill_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(_root()):
        raise ChannelSkillError("A skill deve permanecer na biblioteca local")
    return directory


def parse(skill_id, raw):
    _directory(skill_id)
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_FILE_BYTES:
        raise ChannelSkillError("SKILL.md deve conter de 1 a 24000 bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise ChannelSkillError("Salve SKILL.md em UTF-8") from None
    if not text.strip() or "\x00" in text:
        raise ChannelSkillError("A skill não contém instruções de texto válidas")
    metadata = {}
    if text.startswith("---\n") or text.startswith("---\r\n"):
        lines = text.splitlines()
        closing = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
        if closing is None:
            raise ChannelSkillError("O cabeçalho YAML precisa terminar com ---")
        try:
            metadata = yaml.safe_load("\n".join(lines[1:closing])) or {}
        except yaml.YAMLError:
            raise ChannelSkillError("Cabeçalho YAML inválido") from None
        if not isinstance(metadata, dict) or len(metadata) > 30:
            raise ChannelSkillError("Cabeçalho YAML deve ser um objeto simples")
        if not "\n".join(lines[closing + 1:]).strip():
            raise ChannelSkillError("Escreva as instruções editoriais após o cabeçalho")
    name = metadata.get("name", skill_id)
    version = metadata.get("version", "")
    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise ChannelSkillError("O nome da skill deve ser um texto de até 160 caracteres")
    if not isinstance(version, (str, int, float)) or len(str(version)) > 80:
        raise ChannelSkillError("A versão da skill deve ser um texto curto")
    return ChannelSkillSnapshot(skill_id=skill_id, name=name.strip(), version=str(version),
                                content=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def load(skill_id):
    file = _directory(skill_id) / "SKILL.md"
    try:
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_FILE_BYTES:
            raise ChannelSkillError("SKILL.md ausente ou inválido na biblioteca")
        with file.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise ChannelSkillError("Não foi possível ler SKILL.md na biblioteca") from None
    return parse(skill_id, raw)


def installed():
    result = []
    for directory in sorted(_root().iterdir()):
        if directory.is_dir() and not directory.name.startswith("_"):
            try:
                result.append(load(directory.name))
            except ChannelSkillError:
                continue
    return result


def save(skill_id, raw, *, replace=False):
    snapshot = parse(skill_id, raw)
    directory = _directory(skill_id)
    directory.mkdir(exist_ok=True)
    with FileLock(str(directory / "edit.lock")):
        target = directory / "SKILL.md"
        if target.is_symlink():
            raise ChannelSkillError("SKILL.md não pode ser um link simbólico")
        if target.exists():
            if not replace:
                raise ChannelSkillError("Esse identificador já existe. Selecione a skill para editar ou use outro identificador")
            previous = load(skill_id)
            history = directory / "revisions"
            if history.is_symlink():
                raise ChannelSkillError("Diretório de revisões inválido")
            history.mkdir(exist_ok=True)
            backup = history / (previous.sha256 + ".md")
            if not backup.exists():
                _atomic(backup, previous.content.encode("utf-8"))
        _atomic(target, snapshot.content.encode("utf-8"))
    return snapshot


def remove(skill_id):
    directory = _directory(skill_id)
    with FileLock(str(_root() / "library.lock")):
        load(skill_id)
        trash = _root() / "_trash"
        if trash.is_symlink():
            raise ChannelSkillError("Diretório de arquivo inválido")
        trash.mkdir(exist_ok=True)
        directory.rename(trash / (skill_id + "-" + uuid4().hex))
