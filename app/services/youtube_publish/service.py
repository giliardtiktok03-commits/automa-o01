"""Durable resumable uploads. Ambiguous initiation never creates another upload."""
import hashlib
import io
import json
import math
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from filelock import FileLock,Timeout
from PIL import Image
from app.utils import utils
from .store import Store,PublishError,channel_key,put,read,digest
from . import auth

UPLOAD='https://www.googleapis.com/upload/youtube/v3/videos'
THUMBNAIL='https://www.googleapis.com/upload/youtube/v3/thumbnails/set'
CHUNK=8*1024*1024
_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='youtube-publish')


def video_file(value):
    root=Path(utils.task_dir()).resolve();p=Path(value)
    if p.is_symlink() or not p.is_file() or not p.stat().st_size or not p.resolve().is_relative_to(root):
        raise PublishError('Selecione um vídeo final salvo na pasta de tarefas do MPT')
    if not re.fullmatch(r'final-\d+\.mp4',p.name) or not re.fullmatch(r'[a-f0-9-]{36}',p.parent.name):
        raise PublishError('Este módulo aceita vídeos finais de projetos individuais do MPT')
    return p.resolve()


def metadata(title,description,tags,privacy,made_for_kids):
    if not isinstance(title,str) or not 1<=len(title.strip())<=100 or any(c in title for c in '<>\x00'):
        raise PublishError('Título do YouTube deve ter de 1 a 100 caracteres, sem < ou >')
    if not isinstance(description,str) or not description.strip() or len(description.encode())>5000 or any(c in description for c in '<>\x00'):
        raise PublishError('Informe uma descrição completa com até 5.000 bytes, sem < ou >')
    if privacy not in {'private','unlisted','public'} or not isinstance(made_for_kids,bool):raise PublishError('Privacidade ou declaração de público inválida')
    if not isinstance(tags,list) or any(not isinstance(t,str) or not t.strip() or any(c in t for c in '<>\x00') for t in tags):raise PublishError('Tags inválidas')
    tags=list(dict.fromkeys(t.strip() for t in tags))
    if sum(len(t)+(2 if ' ' in t else 0) for t in tags)+max(0,len(tags)-1)>500:raise PublishError('Tags excedem o limite de 500 caracteres')
    return {'snippet':{'title':title.strip(),'description':description,'tags':tags,'categoryId':'27'},
            'status':{'privacyStatus':privacy,'selfDeclaredMadeForKids':made_for_kids}}


def save_thumbnail(raw,store=None):
    store=store or Store()
    try:
        if not raw or len(raw)>2*1024*1024:raise ValueError()
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {'JPEG','PNG'} or im.width<640 or im.width*im.height>40_000_000:raise ValueError()
            ext='jpg' if im.format=='JPEG' else 'png';im.verify()
    except Exception:raise PublishError('Thumbnail precisa ser JPG/PNG válido, largura mínima de 640 px e até 2 MB') from None
    name=hashlib.sha256(raw).hexdigest()+'.'+ext
    path=store.root/'thumbnails'/name
    if not path.exists():
        from app.utils.atomic_files import write_bytes_atomic
        write_bytes_atomic(path,raw)
    return name


def thumbnail_file(name,store):
    if not re.fullmatch(r'[0-9a-f]{64}\.(jpg|png)',str(name)):raise PublishError('Selecione uma thumbnail válida')
    p=store.root/'thumbnails'/name
    if p.is_symlink() or not p.is_file() or digest(p)!=name.split('.')[0]:raise PublishError('Thumbnail ausente ou alterada')
    return p


def verify_video(path):
    # Reuse the recovery verifier when a mixed scene plan is available.
    if path.name=='final-1.mp4' and (path.parent/'mixed-scenes.json').exists():
        from app.services.autopilot.worker import verify_final
        return verify_final(path.parent)
    try:
        from moviepy import VideoFileClip
        with VideoFileClip(str(path)) as clip:
            duration=float(clip.duration)
            if not math.isfinite(duration) or duration<=0 or clip.audio is None:raise ValueError()
        result=subprocess.run([utils.get_ffmpeg_binary(),'-nostdin','-v','error','-xerror','-i',str(path),
            '-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True,timeout=1800,check=False)
        if result.returncode:raise ValueError()
        return {'sha256':digest(path),'duration':duration,'decode_verified':True}
    except Exception:raise PublishError('Vídeo sem áudio/vídeo válido ou incompleto; confira a renderização') from None


def safe_session_url(url):
    p=urlparse(str(url))
    if p.scheme!='https' or p.hostname not in {'www.googleapis.com','youtube.googleapis.com'} or p.username or p.password or p.port not in (None,443) or not p.path.startswith('/upload/youtube/v3/videos'):
        raise PublishError('Sessão de upload fora do endpoint oficial permitido')
    return url


def remote_error(response,job,store):
    allowed={'quotaExceeded','dailyLimitExceeded','uploadLimitExceeded','rateLimitExceeded','userRateLimitExceeded',
             'forbidden','insufficientPermissions','invalidCredentials','youtubeSignupRequired','invalidTitle','invalidDescription','invalidTags','invalidVideoMetadata','forbiddenPrivacySetting'}
    try:reason=response.json().get('error',{}).get('errors',[{}])[0].get('reason','unknown')
    except Exception:reason='unknown'
    if reason not in allowed:reason='unknown'
    quota=reason in {'quotaExceeded','dailyLimitExceeded','uploadLimitExceeded'}
    if quota:
        now=datetime.now(ZoneInfo('America/Los_Angeles'))
        next_day=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        job.update(state='quota_wait',retry_after=next_day.timestamp())
    else:job.update(state='paused',retry_after=time.time()+300 if response.status_code==429 else 0)
    raw_retry=response.headers.get('Retry-After')
    if raw_retry:
        try:
            try:deadline=time.time()+float(raw_retry)
            except (TypeError,ValueError):deadline=parsedate_to_datetime(raw_retry).timestamp()
            if math.isfinite(deadline):job['retry_after']=max(job.get('retry_after',0),deadline)
        except (TypeError,ValueError,OverflowError):pass
    job['error']=f'YouTube HTTP {response.status_code} ({reason}). Confira permissões, cota e limite do canal antes de retomar.'
    store.save_job(job)
    raise PublishError(job['error'])


def prepare(channel,video,title,description,tags,thumbnail,privacy='private',made_for_kids=False,*,automatic=False,store=None):
    store=store or Store();channel_key(channel);account=store.connection(channel)
    if not account.get('connected'):raise PublishError('Conecte o canal primeiro')
    path=video_file(video);thumb=thumbnail_file(thumbnail,store)
    body=metadata(title,description,tags,privacy,made_for_kids)
    from app.services.historical_archive.commons_credits import locate,has_commons,prepare_description
    folder=locate(path)
    if automatic and folder is not None and has_commons(folder):raise PublishError('Vídeos com Commons continuam exigindo revisão e envio manual')
    body['snippet']['description']=prepare_description(path,description)
    checksum=digest(path)
    key=hashlib.sha256((account['youtube_channel_id']+':'+checksum).encode()).hexdigest()
    with FileLock(str(store.root/'jobs'/(key+'.prepare.lock')),timeout=10):
        old=store.job(key)
        if old:return old  # Never create a second upload for the same bytes/channel.
        job={'id':key,'channel_id':channel,'youtube_channel_id':account['youtube_channel_id'],
             'video':str(path),'video_sha256':checksum,'video_bytes':path.stat().st_size,
             'thumbnail':thumb.name,'metadata':body,'automatic':bool(automatic),
             'state':'prepared','created':time.time(),'updated':time.time(),'video_id':None,'offset':0}
        store.save_job(job)
    return job


def _accepted(response,job,store):
    if response.status_code not in (200,201):return False
    value=response.json().get('id','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',value):raise PublishError('Resposta de upload sem ID válido; revise a sessão antes de reenviar')
    job.update(video_id=value,url='https://www.youtube.com/watch?v='+value,state='thumbnail_pending',offset=job['video_bytes'],error=None)
    store.save_job(job)
    return True


def execute(key,store=None,session_factory=None,verifier=None):
    store=store or Store();factory=session_factory or auth.session
    try:
        with FileLock(str(store.root/'jobs'/(key+'.worker.lock')),timeout=0):
            job=store.job(key)
            if not job:raise PublishError('Postagem não encontrada')
            if job['state']=='completed':return job
            if job.get('retry_after',0)>time.time():raise PublishError('Aguarde a renovação da cota/espera antes de retomar')
            # Recheck locally before any Google request, even for a saved upload session.
            path=video_file(job['video'])
            if digest(path)!=job['video_sha256'] or path.stat().st_size!=job['video_bytes']:raise PublishError('O vídeo mudou após preparar a postagem')
            thumb=thumbnail_file(job['thumbnail'],store)
            if not job.get('qa'):
                qa=(verifier or verify_video)(path)
                if not qa.get('decode_verified') or qa.get('sha256')!=job['video_sha256']:raise PublishError('Verificação técnica do vídeo não foi aprovada')
                job['qa']=qa;store.save_job(job)
            from app.services.historical_archive.commons_credits import locate,has_commons,prepare_description
            folder=locate(path)
            if job['automatic'] and folder is not None and has_commons(folder):raise PublishError('Commons exige envio manual após revisão')
            job['metadata']['snippet']['description']=prepare_description(path,job['metadata']['snippet']['description'])
            account=store.connection(job['channel_id'])
            if not account.get('connected') or account.get('youtube_channel_id')!=job['youtube_channel_id']:raise PublishError('Conexão do canal mudou; confira a autorização')
            if job['automatic'] and not account.get('auto_upload'):raise PublishError('Envio automático foi desativado para este canal')
            session_path=store.root/'private'/(key+'.session.json')
            saved=read(session_path,{})
            if not job.get('video_id') and not saved and job.get('upload_started'):
                raise PublishError('Início de envio sem confirmação. Revise no YouTube Studio; não será criado outro upload automaticamente')
            with factory(job['channel_id'],store) as api:
                if auth.identity(api)['youtube_channel_id']!=job['youtube_channel_id']:raise PublishError('Canal autorizado diferente do destino salvo')
                if not job.get('video_id'):
                    if not saved:
                        job.update(state='initiating',error=None,upload_started=True);store.save_job(job)
                        r=api.post(UPLOAD,params={'uploadType':'resumable','part':'snippet,status'},json={**job['metadata'],'status':{**job['metadata']['status'],'privacyStatus':'private'}},
                            headers={'X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':str(job['video_bytes'])},timeout=60,allow_redirects=False)
                        if r.status_code not in (200,201):
                            if 400<=r.status_code<500:job['upload_started']=False;store.save_job(job)
                            remote_error(r,job,store)
                        url=safe_session_url(r.headers.get('Location',''))
                        saved={'url':url};put(session_path,saved,private=True)
                        job.update(state='uploading');store.save_job(job)
                    url=safe_session_url(saved['url'])
                    # Always ask the server, rather than trusting a locally saved byte offset.
                    r=api.put(url,data=b'',headers={'Content-Length':'0','Content-Range':f"bytes */{job['video_bytes']}"},timeout=60,allow_redirects=False)
                    if not _accepted(r,job,store):
                        if r.status_code!=308:remote_error(r,job,store)
                        value=r.headers.get('Range','')
                        match=re.fullmatch(r'bytes=0-(\d+)',value) if value else None
                        if value and not match:raise PublishError('Resposta de progresso de upload inválida')
                        offset=int(match[1])+1 if match else 0
                        if not 0<=offset<job['video_bytes']:raise PublishError('Progresso de upload fora do arquivo')
                        with path.open('rb') as stream:
                            stream.seek(offset)
                            while offset<job['video_bytes']:
                                block=stream.read(min(CHUNK,job['video_bytes']-offset))
                                if not block:raise PublishError('Vídeo truncado durante o upload')
                                end=offset+len(block)-1
                                r=api.put(url,data=block,headers={'Content-Type':'video/mp4','Content-Length':str(len(block)),
                                    'Content-Range':f"bytes {offset}-{end}/{job['video_bytes']}"},timeout=120,allow_redirects=False)
                                if _accepted(r,job,store):break
                                if r.status_code!=308:remote_error(r,job,store)
                                if r.headers.get('Range')!=f'bytes=0-{end}':raise PublishError('Confirmação parcial inesperada; retome para consultar o servidor')
                                offset=end+1;job.update(offset=offset,state='uploading');store.save_job(job)
                        if not job.get('video_id'):raise PublishError('YouTube ainda não confirmou o vídeo; retome para consultar a sessão')
                if digest(path)!=job['video_sha256']:
                    raise PublishError('O arquivo mudou durante o envio. O vídeo permanece privado e exige revisão.')
                # Existing video ID is durable before attaching the thumbnail: retries never reupload.
                if not job.get('thumbnail_uploaded'):
                    with thumb.open('rb') as image:
                        r=api.post(THUMBNAIL,params={'videoId':job['video_id']},data=image,
                            headers={'Content-Type':'image/jpeg' if thumb.suffix=='.jpg' else 'image/png'},timeout=60,allow_redirects=False)
                    if r.status_code!=200:remote_error(r,job,store)
                    job['thumbnail_uploaded']=True;store.save_job(job)
                # Public/unlisted visibility is applied only after all assets are attached.
                if job['metadata']['status']['privacyStatus']!='private':
                    job.update(state='privacy_pending');store.save_job(job)
                    r=api.put(auth.API+'/videos',params={'part':'status'},
                        json={'id':job['video_id'],'status':job['metadata']['status']},timeout=60,allow_redirects=False)
                    if r.status_code!=200:remote_error(r,job,store)
                    if r.json().get('status',{}).get('privacyStatus')!=job['metadata']['status']['privacyStatus']:
                        raise PublishError('YouTube não confirmou a visibilidade solicitada. Confira as restrições de auditoria do projeto')
                job.update(state='completed',error=None,retry_after=0);store.save_job(job)
                session_path.unlink(missing_ok=True)
                return job
    except Timeout:raise PublishError('Esta postagem já está sendo processada') from None
    except Exception as exc:
        job=store.job(key)
        if job and job.get('state')!='completed':
            if job.get('state') not in {'quota_wait','paused'}:job['state']='paused'
            job['error']=str(exc) if isinstance(exc,PublishError) else 'Envio interrompido ('+type(exc).__name__+'). Retome a sessão salva; não reenvie como outra tarefa.'
            store.save_job(job)
        if isinstance(exc,PublishError):raise
        raise PublishError(job['error'] if job else 'Falha local na postagem') from None


def submit(key,store=None):
    store=store or Store();job=store.job(key)
    if not job:raise PublishError('Postagem não encontrada')
    if job.get('retry_after',0)>time.time():raise PublishError('Aguarde a renovação da cota/espera antes de retomar')
    def run():
        try:execute(key,store)
        except Exception:pass  # Safe error is already persisted; never log OAuth/session data.
    _pool.submit(run)


def after_generation(params,videos):
    """Capture explicit new-task settings; generation success never depends on upload."""
    snapshot=getattr(params,'youtube_publication',{}) or {}
    if not snapshot.get('auto_upload'):return None
    try:
        if len(videos)!=1:raise PublishError('Envio automático requer um único vídeo final')
        from app.config import config
        if config.app.get('upload_post_enabled') and config.app.get('upload_post_auto_upload') and 'youtube' in config.app.get('upload_post_platforms',[]):
            raise PublishError('Escolha apenas um envio automático para YouTube: direto ou Upload-Post')
        store=Store();account=store.connection(snapshot['channel_id'])
        if account.get('youtube_channel_id')!=snapshot['youtube_channel_id']:raise PublishError('Canal de destino mudou após o início da geração')
        job=prepare(snapshot['channel_id'],videos[0],params.video_subject,snapshot['description'],snapshot['tags'],
            snapshot['thumbnail'],snapshot['privacy'],snapshot['made_for_kids'],automatic=True,store=store)
        submit(job['id'],store)
        return {'job_id':job['id'],'state':job['state']}
    except Exception as exc:
        error=str(exc) if isinstance(exc,PublishError) else 'Postagem não foi agendada; confira o módulo YouTube'
        # Visible durable notice even when preflight prevents creating an upload record.
        if videos:
            path=Path(videos[0]).parent/'youtube-publication-status.json'
            put(path,{'state':'needs_review','error':error,'published':False})
        return {'state':'needs_review','error':error}
