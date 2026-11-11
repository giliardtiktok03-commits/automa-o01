"""Install once without activating, overwriting edits or undoing an archive."""
from pathlib import Path
from filelock import FileLock
from app.services import channel_skills
from app.utils.atomic_files import write_bytes_atomic

SKILL_ID = 'historical-documentary-director'
BUNDLE = Path(__file__).resolve().parents[3] / 'resource' / 'channel-skills' / SKILL_ID / 'SKILL.md'


def install():
    root=channel_skills._root()
    marker=root/'_historical-director-installed.json'
    with FileLock(str(root/'library.lock')):
        if marker.exists():
            return
        target=channel_skills._directory(SKILL_ID)/'SKILL.md'
        if not target.exists():
            channel_skills.save(SKILL_ID,BUNDLE.read_bytes())
        write_bytes_atomic(marker,b'{"version":"1.1"}')
