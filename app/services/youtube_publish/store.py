"""Separate, durable channel connections and idempotent publication records."""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from filelock import FileLock
from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic


class PublishError(ValueError):
    pass


def channel_key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,47}',value):
        raise PublishError('Selecione um canal cadastrado no AUTOPILOT')
    return value


def put(path,value,private=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise PublishError('Arquivo de publicação não pode ser link simbólico')
    write_bytes_atomic(path,json.dumps(value,ensure_ascii=False,indent=2).encode())
    if private:
        os.chmod(path,0o600)


def read(path,default=None):
    path=Path(path)
    if not path.exists():return default
    if path.is_symlink() or path.stat().st_size>4*1024*1024:raise PublishError('Registro local inválido')
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError):raise PublishError('Registro local inválido; preserve os arquivos para revisão') from None


def digest(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):sha.update(block)
    return sha.hexdigest()


class Store:
    def __init__(self,root=None):
        self.root=Path(root) if root else Path(utils.storage_dir('youtube_publish',create=True))
        self.root.mkdir(parents=True,exist_ok=True)
        for name in ('connections','jobs','private','thumbnails'):
            p=self.root/name
            if p.is_symlink():raise PublishError('Pasta de publicação inválida')
            p.mkdir(exist_ok=True)
        os.chmod(self.root/'private',0o700)

    def connection(self,channel):
        return read(self.root/'connections'/(channel_key(channel)+'.json'),{})

    def save_connection(self,channel,value):
        with FileLock(str(self.root/'connections'/(channel_key(channel)+'.lock')),timeout=10):
            put(self.root/'connections'/(channel_key(channel)+'.json'),value)

    def secret_path(self,channel):
        return self.root/'private'/(channel_key(channel)+'.json')

    def job(self,key):
        if not re.fullmatch(r'[0-9a-f]{64}',str(key)):raise PublishError('ID de postagem inválido')
        return read(self.root/'jobs'/(key+'.json'))

    def save_job(self,job):
        if not re.fullmatch(r'[0-9a-f]{64}',str(job.get('id'))):raise PublishError('ID de postagem inválido')
        job['updated']=time.time();put(self.root/'jobs'/(job['id']+'.json'),job)

    def jobs(self,channel):
        channel_key(channel)
        jobs=[read(p) for p in (self.root/'jobs').glob('*.json')]
        return sorted([j for j in jobs if j and j.get('channel_id')==channel],key=lambda j:j['updated'],reverse=True)[:30]
