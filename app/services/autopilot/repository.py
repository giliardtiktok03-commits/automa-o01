"""SQLite journal. No credentials, media copies or process-only job identity."""
from contextlib import contextmanager
import hashlib
import unicodedata
import json
import re
from pathlib import Path
import sqlite3
import time
from uuid import UUID

from app.models.autopilot import ChannelProfile
from app.services.historical_director.repository import DirectorRepositoryMixin, SCHEMA as DIRECTOR_SCHEMA
from app.utils import utils


class Conflict(ValueError):
    pass


class Repository(DirectorRepositoryMixin):
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path(utils.storage_dir("autopilot", create=True)) / "autopilot.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
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
                CREATE TABLE IF NOT EXISTS editorial_jobs (
                    task_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL REFERENCES channels(channel_id),
                    title TEXT NOT NULL, identity_hash TEXT NOT NULL UNIQUE,
                    snapshot TEXT NOT NULL, state TEXT NOT NULL, error TEXT, result TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS editorial_stages (
                    task_id TEXT NOT NULL REFERENCES editorial_jobs(task_id),
                    name TEXT NOT NULL, remote INTEGER NOT NULL, state TEXT NOT NULL,
                    result TEXT, digest TEXT, updated REAL NOT NULL,
                    PRIMARY KEY(task_id,name)
                );
                CREATE TABLE IF NOT EXISTS editorial_history (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES editorial_jobs(task_id),
                    stages TEXT NOT NULL, created REAL NOT NULL
                );

            """)
            db.executescript(DIRECTOR_SCHEMA + "\nPRAGMA user_version = 3;")

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

    def submit_editorial(self, title, snapshot):
        from uuid import uuid4
        from app.models.autopilot_editorial import EditorialSnapshot
        snapshot = EditorialSnapshot.model_validate(snapshot)
        title = title.strip()
        if not title or len(title) > 300 or '\x00' in title:
            raise ValueError("Informe um título de até 300 caracteres")
        canonical_title = ' '.join(unicodedata.normalize('NFKC', title).casefold().split())
        identity = hashlib.sha256((snapshot.channel.channel_id + '\0' + canonical_title).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT task_id FROM editorial_jobs WHERE identity_hash=?', (identity,)).fetchone()
            if prior:
                return prior[0], False
            row = db.execute('SELECT profile FROM channels WHERE channel_id=?', (snapshot.channel.channel_id,)).fetchone()
            if not row or ChannelProfile.model_validate_json(row[0]) != snapshot.channel:
                raise Conflict("O canal mudou antes do envio; confira e tente novamente")
            if not snapshot.channel.auto_editorial:
                raise Conflict("Autorize pesquisa e roteiro automáticos nas configurações do canal")
            task_id, now = str(uuid4()), time.time()
            db.execute('INSERT INTO editorial_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (task_id, snapshot.channel.channel_id, title, identity, snapshot.model_dump_json(), 'queued', None, None, now, now))
            return task_id, True

    def editorial_jobs(self, *, limit=50):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM editorial_jobs ORDER BY created DESC LIMIT ?', (limit,))]

    def get_editorial(self, task_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM editorial_jobs WHERE task_id=?', (task_id,)).fetchone()
            return dict(row) if row else None

    def take_editorial(self):
        self.prepare_director_automatic()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            enabled = db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()
            if not enabled or enabled[0] != 'true':
                return None
            for row in db.execute("SELECT * FROM editorial_jobs WHERE state IN ('queued','running') ORDER BY created").fetchall():
                if not self.director_available(db, row):
                    continue
                channel = db.execute('SELECT profile FROM channels WHERE channel_id=?', (row['channel_id'],)).fetchone()
                if not channel or not ChannelProfile.model_validate_json(channel[0]).auto_editorial:
                    continue
                db.execute("UPDATE editorial_jobs SET state='running',error=NULL,updated=? WHERE task_id=?", (time.time(), row['task_id']))
                db.execute("UPDATE director_batches SET state='running',updated=? WHERE batch_id IN (SELECT batch_id FROM director_items WHERE task_id=? AND role='production')", (time.time(), row['task_id']))
                return {**dict(row), 'kind': 'editorial'}
        return None

    def stages(self, task_id):
        with self.connect() as db:
            return {row['name']: dict(row) for row in db.execute('SELECT * FROM editorial_stages WHERE task_id=?', (task_id,))}

    def begin_stage(self, task_id, name, *, remote):
        from app.services.autopilot.recovery import RecoveryBlocked
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM editorial_stages WHERE task_id=? AND name=?', (task_id, name)).fetchone()
            if row and row['state'] == 'completed':
                if hashlib.sha256(row['result'].encode()).hexdigest() != row['digest']:
                    raise RecoveryBlocked("Artefato editorial alterado; revise antes de repetir uma chamada paga")
                return json.loads(row['result'])
            if row and (row['remote'] or row['state'] == 'failed'):
                raise RecoveryBlocked("Etapa remota interrompida ou com falha. Revise antes de autorizar outra chamada")
            db.execute("INSERT INTO editorial_stages VALUES(?,?,?,'running',NULL,NULL,?) ON CONFLICT(task_id,name) DO UPDATE SET state='running',updated=excluded.updated",
                       (task_id, name, int(remote), time.time()))
            return None

    def complete_stage(self, task_id, name, value):
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connect() as db:
            db.execute("UPDATE editorial_stages SET state='completed',result=?,digest=?,updated=? WHERE task_id=? AND name=? AND state='running'",
                       (encoded, digest, time.time(), task_id, name))

    def fail_stage(self, task_id, name):
        with self.connect() as db:
            db.execute("UPDATE editorial_stages SET state='failed',updated=? WHERE task_id=? AND name=? AND state='running'", (time.time(), task_id, name))

    def finish_editorial(self, task_id, state, *, error=None, result=None):
        if state not in {'completed', 'blocked', 'failed', 'paused', 'cancelled'}:
            raise ValueError('Estado editorial inválido')
        with self.connect() as db:
            changed = db.execute("UPDATE editorial_jobs SET state=?,error=?,result=?,updated=? WHERE task_id=? AND state='running'",
                       (state, error, json.dumps(result, ensure_ascii=False) if result else None, time.time(), task_id)).rowcount
            if changed:
                self.director_finished(db, task_id, state, result, error)

    def retry_editorial(self, task_id, *, restart=False, acknowledge_cost=False):
        if not acknowledge_cost:
            raise Conflict("Confirme que repetir uma etapa remota pode consumir saldo")
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT state FROM editorial_jobs WHERE task_id=?', (task_id,)).fetchone()
            if not job or job[0] not in {'failed', 'blocked'}:
                return False
            if db.execute('SELECT 1 FROM director_items WHERE task_id=?', (task_id,)).fetchone() and db.execute('SELECT count(*) FROM editorial_history WHERE task_id=?', (task_id,)).fetchone()[0] >= 3:
                raise Conflict('Limite de 3 tentativas adicionais atingido; revise e crie uma nova versão explícita do lote')
            history = [dict(row) for row in db.execute('SELECT * FROM editorial_stages WHERE task_id=?', (task_id,))]
            db.execute('INSERT INTO editorial_history(task_id,stages,created) VALUES(?,?,?)', (task_id, json.dumps(history, ensure_ascii=False), time.time()))
            if restart:
                db.execute('DELETE FROM editorial_stages WHERE task_id=?', (task_id,))
            else:
                db.execute("DELETE FROM editorial_stages WHERE task_id=? AND state!='completed'", (task_id,))
            db.execute("UPDATE editorial_jobs SET state='queued',error=NULL,updated=? WHERE task_id=?", (time.time(), task_id))
            return True
