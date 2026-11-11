"""SQLite journal. No credentials, media copies or process-only job identity."""
from contextlib import contextmanager
import json
import re
from pathlib import Path
import sqlite3
import time
from uuid import UUID

from app.models.autopilot import ChannelProfile
from app.utils import utils


class Conflict(ValueError):
    pass


class Repository:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path(utils.storage_dir("autopilot", create=True)) / "autopilot.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Versão AUTOPILOT incompatível; atualize o programa")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                    profile TEXT NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    task_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL REFERENCES channels(channel_id),
                    channel_version INTEGER NOT NULL, profile TEXT NOT NULL,
                    title TEXT NOT NULL, editorial_digest TEXT NOT NULL, state TEXT NOT NULL,
                    error TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL, next_attempt REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id TEXT REFERENCES jobs(task_id),
                    kind TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def channels(self):
        with self.connect() as db:
            return [{"version": row["version"], **json.loads(row["profile"])} for row in db.execute("SELECT * FROM channels ORDER BY channel_id")]

    def save_channel(self, profile, *, expected_version=0):
        profile = ChannelProfile.model_validate(profile)
        value = profile.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM channels WHERE channel_id=?", (profile.channel_id,)).fetchone()
            version = row[0] if row else 0
            if expected_version != version:
                raise Conflict("O canal foi alterado em outra sessão; recarregue antes de salvar")
            version += 1
            db.execute("INSERT INTO channels VALUES(?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET version=excluded.version,profile=excluded.profile,updated=excluded.updated",
                       (profile.channel_id, version, value, time.time()))
            return version

    def enroll(self, task_id, channel_id, title, editorial_digest):
        task_id = str(UUID(str(task_id)))
        if not re.fullmatch(r"[0-9a-f]{64}", editorial_digest):
            raise ValueError("Identidade editorial inválida")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            channel = db.execute("SELECT * FROM channels WHERE channel_id=?", (channel_id,)).fetchone()
            if channel is None:
                raise ValueError("Canal não cadastrado")
            existing = db.execute("SELECT * FROM jobs WHERE task_id=?", (task_id,)).fetchone()
            if existing:
                if existing["channel_id"] != channel_id:
                    raise Conflict("Este projeto já pertence a outro canal no AUTOPILOT")
                return False
            now = time.time()
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (task_id, channel_id, channel["version"], channel["profile"], title[:300], editorial_digest, "queued", None, None, now, now, 0))
            db.execute("INSERT INTO events(task_id,kind,created) VALUES(?,?,?)", (task_id, "enrolled", now))
            return True

    def jobs(self, *, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created DESC,task_id LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE task_id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def enabled(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()
            return row is not None and row[0] == "true"

    def set_enabled(self, enabled):
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES('enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("true" if enabled else "false",))

    def take(self):
        """Called only while the OS-owned worker lock is held, including recovery."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            enabled = db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()
            if enabled is None or enabled[0] != "true":
                return None
            rows = db.execute("SELECT * FROM jobs WHERE state IN ('queued','running','waiting_remote') AND next_attempt<=? ORDER BY created,task_id", (time.time(),)).fetchall()
            for row in rows:
                channel = db.execute("SELECT profile FROM channels WHERE channel_id=?", (row["channel_id"],)).fetchone()
                if not channel or not json.loads(channel[0])["auto_resume"]:
                    continue
                db.execute("UPDATE jobs SET state='running',error=NULL,updated=? WHERE task_id=?", (time.time(), row["task_id"]))
                db.execute("INSERT INTO events(task_id,kind,created) VALUES(?,?,?)", (row["task_id"], "recovered" if row["state"] == "running" else "started", time.time()))
                return dict(row)
        return None

    def finish(self, task_id, state, *, error=None, result=None):
        if state not in {"queued", "completed", "blocked", "failed", "cancelled", "waiting_remote"}:
            raise ValueError("Estado inválido")
        with self.connect() as db:
            db.execute("UPDATE jobs SET state=?,error=?,result=?,updated=?,next_attempt=? WHERE task_id=? AND state='running'", (state, error, json.dumps(result, ensure_ascii=False) if result else None, time.time(), time.time() + 30 if state == "waiting_remote" else 0, task_id))
            db.execute("INSERT INTO events(task_id,kind,created) VALUES(?,?,?)", (task_id, state, time.time()))

    def retry(self, task_id, *, refresh_profile=False):
        """Explicit retry; never silently resets a completed or actively running job."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if refresh_profile:
                db.execute("UPDATE jobs SET profile=(SELECT profile FROM channels WHERE channels.channel_id=jobs.channel_id),channel_version=(SELECT version FROM channels WHERE channels.channel_id=jobs.channel_id) WHERE task_id=? AND state IN ('failed','blocked','waiting_remote')", (task_id,))
            changed = db.execute("UPDATE jobs SET state='queued',error=NULL,next_attempt=0,updated=? WHERE task_id=? AND state IN ('failed','blocked','waiting_remote')", (time.time(), task_id)).rowcount
            return bool(changed)
