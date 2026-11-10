"""Official APIs only, bounded reads, cancellation, cache, per-provider pacing."""
import hashlib
import json
import random
import math
import threading
import time
from datetime import datetime,timezone
from filelock import FileLock
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from app.utils.atomic_files import write_bytes_atomic
from .contracts import ArchiveError, ArchiveDisabled

_LOCKS={}
_GUARD=threading.Lock()
_NEXT={}
_ALLOWED=('loc.gov','archives.gov','wikimedia.org','nara-media.s3.amazonaws.com')


def safe_url(url):
    value=urlparse(url)
    host=value.hostname or ''
    official=any(host==d or host.endswith('.'+d) for d in _ALLOWED) or (host=='s3.amazonaws.com' and value.path.startswith('/NARAprodstorage/'))
    if value.scheme!='https' or value.username or value.password or value.port not in (None,443) or not official:
        raise ArchiveError('URL fora dos domínios oficiais permitidos')
    return url


def loc_bucket(provider,url):
    parsed=urlparse(url)
    host=parsed.hostname or ''
    if not (host=='loc.gov' or host.endswith('.loc.gov')):return provider
    path=parsed.path.lower()
    if host in {'loc.gov','www.loc.gov'} and path.startswith(('/search','/item/','/pictures/item/','/resource/')):
        return 'loc_json'
    if provider=='loc_text' or path.startswith('/text-services/') or path.endswith(('.txt','.xml','.alto','.hocr')):
        return 'loc_text'
    if provider=='loc_image' or path.startswith('/image-services/') or path.endswith(('.jpg','.jpeg','.png','.tif','.tiff','.jp2','.webp')):
        return 'loc_image'
    return 'loc_json'


class Transport:
    def __init__(self,cache,settings,active):
        self.cache=Path(cache)
        self.settings=settings
        self.active=active

    def check(self):
        if not self.active():raise ArchiveDisabled('Pesquisa histórica desativada ou cancelada')

    def pause(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            self.check()
            time.sleep(min(.1,max(0,end-time.monotonic())))

    def _cooldown_paths(self,bucket):
        paths=[self.cache/(bucket+'-cooldown.json')]
        if bucket.startswith('loc_'):paths.append(self.cache/'loc-cooldown.json')
        return paths

    def _check_cooldown(self,bucket):
        for path in self._cooldown_paths(bucket):
            until=0
            if path.exists():
                try:until=float(json.loads(path.read_text())['until'])
                except (OSError,ValueError,KeyError):pass
            if until>time.time():raise ArchiveError('Provider em espera após bloqueio/rate limit; sem novas tentativas nesta execução')

    def _record_cooldown(self,bucket,response):
        default=self.settings.loc_block_cooldown_seconds if bucket.startswith('loc_') else 60
        retry=response.headers.get('Retry-After',str(default))
        try:wait=float(retry)
        except (TypeError,ValueError):
            try:wait=parsedate_to_datetime(retry).timestamp()-time.time()
            except Exception:wait=default
        if not math.isfinite(wait):wait=default
        self.cache.mkdir(parents=True,exist_ok=True)
        for path in self._cooldown_paths(bucket):
            with FileLock(str(path)+'.lock',timeout=self.settings.request_timeout_seconds):
                previous=0
                try:previous=float(json.loads(path.read_text())['until']) if path.exists() else 0
                except (OSError,ValueError,KeyError):pass
                if not math.isfinite(previous):previous=0
                write_bytes_atomic(path,json.dumps({'until':max(previous,time.time()+max(1,wait))}).encode())

    def _loc_slot(self,bucket):
        # Persistent rolling 60-second window + spacing, shared between workers/processes.
        # Cached responses do not reserve a slot; every actual attempt/retry does.
        self.cache.mkdir(parents=True,exist_ok=True)
        path=self.cache/(bucket+'-rate.json')
        rpm=getattr(self.settings,bucket+'_rpm')
        spacing=60/rpm
        if bucket=='loc_json':spacing=max(spacing,self.settings.loc_interval_seconds)
        with FileLock(str(path)+'.lock',timeout=self.settings.request_timeout_seconds):
            while True:
                self.check();self._check_cooldown(bucket)
                current=time.time()
                try:data=json.loads(path.read_text()) if path.exists() else {}
                except (OSError,ValueError):data={}
                recent=[t for t in data.get('requests',[]) if isinstance(t,(float,int)) and t>current-60]
                wait=max(0,(max(recent)+spacing-current) if recent else 0)
                if len(recent)>=rpm:wait=max(wait,min(recent)+60-current+.01)
                if wait>0:
                    self.pause(wait)
                    continue
                recent.append(current)
                write_bytes_atomic(path,json.dumps({'requests':recent}).encode())
                return

    def get(self,provider,url,*,params=None,headers=None,max_bytes=5*1024*1024):
        safe_url(url)
        self.check()
        bucket=loc_bucket(provider,url)
        with _GUARD:lock=_LOCKS.setdefault(bucket,threading.Lock())
        with lock:
            self._check_cooldown(bucket)
            if not bucket.startswith('loc_'):self.pause(max(0,_NEXT.get(bucket,0)-time.monotonic()))
            for attempt in range(self.settings.max_retries+1):
                self.check()
                self._check_cooldown(bucket)
                if bucket.startswith('loc_'):self._loc_slot(bucket)
                else:self.pause(max(0,_NEXT.get(bucket,0)-time.monotonic()))
                if provider=='nara':
                    self.cache.mkdir(parents=True,exist_ok=True)
                    usage=self.cache/('nara-usage-'+datetime.now(timezone.utc).strftime('%Y-%m')+'.json')
                    with FileLock(str(usage)+'.lock',timeout=10):
                        used=json.loads(usage.read_text()).get('requests',0) if usage.exists() else 0
                        if used>=self.settings.nara_monthly_limit:raise ArchiveError('Limite mensal local NARA atingido; outras fontes continuam')
                        write_bytes_atomic(usage,json.dumps({'requests':used+1}).encode())
                if not bucket.startswith('loc_'):
                    interval=max(self.settings.request_interval_seconds,getattr(self.settings,provider+'_interval_seconds',0))
                    _NEXT[bucket]=time.monotonic()+interval
                try:
                    with requests.get(url,params=params,headers={'User-Agent':self.settings.user_agent,**(headers or {})},timeout=(5,self.settings.request_timeout_seconds),stream=True,allow_redirects=False) as response:
                        if response.status_code==429 or (bucket.startswith('loc_') and response.status_code==403) or (response.status_code==503 and response.headers.get('Retry-After')):
                            self._record_cooldown(bucket,response)
                            raise ArchiveError('Rate limit/bloqueio temporário; Retry-After preservado, sem insistência nem troca de serviço LOC')
                        if response.status_code in (500,502,503,504) and attempt<self.settings.max_retries:
                            self.pause(2**attempt+random.random())
                            continue
                        if response.status_code!=200:raise ArchiveError(f'Provider HTTP {response.status_code}; sem redirecionamento ou contorno')
                        chunks,size=[],0
                        for chunk in response.iter_content(65536):
                            self.check();size+=len(chunk)
                            if size>max_bytes:raise ArchiveError('Resposta/arquivo excede o limite configurado')
                            chunks.append(chunk)
                        return b''.join(chunks)
                except requests.RequestException:
                    if attempt>=self.settings.max_retries:raise ArchiveError('Provider indisponível ou timeout') from None
                    self.pause(2**attempt+random.random())
        raise ArchiveError('Provider indisponível')

    def json(self,provider,url,*,params=None,headers=None):
        self.check()
        key=hashlib.sha256(json.dumps([provider,url,params],sort_keys=True).encode()).hexdigest()
        target=self.cache/(key+'.json')
        if target.exists() and time.time()-target.stat().st_mtime<self.settings.cache_ttl_hours*3600:
            return json.loads(target.read_text())
        data=json.loads(self.get(provider,url,params=params,headers=headers))
        self.check()
        if isinstance(data,dict) and data.get('error'):raise ArchiveError('Provider devolveu erro de API; consulta interrompida')
        self.cache.mkdir(parents=True,exist_ok=True)
        write_bytes_atomic(target,json.dumps(data,ensure_ascii=False).encode())
        return data


    def cached_bytes(self,provider,url,*,max_bytes=2*1024*1024):
        self.check()
        key=hashlib.sha256(json.dumps([provider,url],sort_keys=True).encode()).hexdigest()
        path=self.cache/(key+'.bin')
        if path.exists() and path.stat().st_size<=max_bytes and time.time()-path.stat().st_mtime<self.settings.cache_ttl_hours*3600:
            return path.read_bytes()
        data=self.get(provider,url,max_bytes=max_bytes)
        self.check()
        self.cache.mkdir(parents=True,exist_ok=True)
        write_bytes_atomic(path,data)
        return data
