"""Official APIs only, bounded reads, cancellation, cache, per-provider pacing."""
import hashlib
import json
import random
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

    def get(self,provider,url,*,params=None,headers=None,max_bytes=5*1024*1024):
        safe_url(url)
        self.check()
        with _GUARD:lock=_LOCKS.setdefault(provider,threading.Lock())
        with lock:
            cooldown=self.cache/(provider+'-cooldown.json')
            until=0
            if cooldown.exists():
                try:until=float(json.loads(cooldown.read_text())['until'])
                except (OSError,ValueError,KeyError):pass
            if until>time.time():raise ArchiveError('Provider em espera após rate limit; tente em outra execução')
            self.pause(max(0,_NEXT.get(provider,0)-time.monotonic()))
            for attempt in range(self.settings.max_retries+1):
                self.check()
                self.pause(max(0,_NEXT.get(provider,0)-time.monotonic()))
                if provider=='nara':
                    self.cache.mkdir(parents=True,exist_ok=True)
                    usage=self.cache/('nara-usage-'+datetime.now(timezone.utc).strftime('%Y-%m')+'.json')
                    with FileLock(str(usage)+'.lock',timeout=10):
                        used=json.loads(usage.read_text()).get('requests',0) if usage.exists() else 0
                        if used>=self.settings.nara_monthly_limit:raise ArchiveError('Limite mensal local NARA atingido; outras fontes continuam')
                        write_bytes_atomic(usage,json.dumps({'requests':used+1}).encode())
                interval=max(self.settings.request_interval_seconds,getattr(self.settings,provider+'_interval_seconds',0))
                _NEXT[provider]=time.monotonic()+interval
                try:
                    with requests.get(url,params=params,headers={'User-Agent':self.settings.user_agent,**(headers or {})},timeout=(5,self.settings.request_timeout_seconds),stream=True,allow_redirects=False) as response:
                        if response.status_code==429:
                            retry=response.headers.get('Retry-After','60')
                            try:wait=float(retry)
                            except ValueError:
                                try:wait=parsedate_to_datetime(retry).timestamp()-time.time()
                                except Exception:wait=60
                            self.cache.mkdir(parents=True,exist_ok=True)
                            write_bytes_atomic(cooldown,json.dumps({'until':time.time()+max(1,wait)}).encode())
                            raise ArchiveError('Rate limit do provider; Retry-After preservado, sem insistência')
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
