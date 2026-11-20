"""AI33PRO v3 narration. One paid POST; durable task ID, verified audio and captions.

Contract verified against https://ai33.pro/app/api-document public documentation.
No credentials or signed asset URLs are stored in checkpoints.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urljoin
from filelock import FileLock
import requests
from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic
from .client import AI33Client,AI33Error,_TransientError
from .provider import api_key
from .images import _public_https

PREFIX='ai33:'
VOICE_PROVIDERS=('elevenlabs','minimax','clone','edge','kokoro','vbee','fishaudio')
TYPES={'tts','v3_tts','edge_tts','elevenlabs_tts','minimax_tts','kokoro_tts','fishaudio_tts','vbee_tts'}


def voice_id(value):
    value=str(value or '').removeprefix(PREFIX).strip()
    if not re.fullmatch(r'(?:elevenlabs|minimax|edge|kokoro|clone|vbee|fishaudio)_[A-Za-z0-9_.:-]{1,170}',value):
        raise AI33Error('Selecione uma voz real do catálogo AI33PRO, com o prefixo do provedor')
    return value


class SpeechClient(AI33Client):
    def voices(self,search='',page=1,*,provider='elevenlabs'):
        if provider not in VOICE_PROVIDERS:raise AI33Error('Selecione um catálogo de vozes AI33PRO válido')
        data=self._request('GET','/v3/voices',params={'provider':provider,'search':search[:200],'page':page,'page_size':100})
        rows=data.get('data')
        if data.get('success') is not True or not isinstance(rows,list):raise AI33Error('Catálogo de vozes AI33 inválido')
        result=[]
        for row in rows:
            if not isinstance(row,dict):continue
            try:identity=voice_id(row.get('voice_id',''))
            except AI33Error:continue
            result.append({'voice_id':identity,'name':str(row.get('name') or identity)[:200],
                'language':str(row.get('language') or '')[:80],'gender':str(row.get('gender') or '')[:40]})
        return {'voices':result,'has_more':(data.get('pagination') or {}).get('has_more') is True}

    def create(self,text,identity,speed):
        data=self._request('POST','/v3/text-to-speech',files=[('text',(None,text)),
            ('voice_id',(None,identity)),('speed',(None,str(speed))),('with_transcript',(None,'true'))])
        identity=data.get('task_id')
        if data.get('success') is not True or not self.valid_task_id(identity):raise AI33Error('AI33 não confirmou o ID da narração; confira o painel antes de repetir')
        return identity

    def speech_task(self,identity):
        if not self.valid_task_id(identity):raise AI33Error('ID da narração AI33 inválido')
        data=self._request('GET','/v1/task/'+identity)
        if data.get('id')!=identity or data.get('type') not in TYPES:raise AI33Error('A tarefa retornada não corresponde à narração AI33 solicitada')
        if data.get('status') not in {'doing','done','error'}:raise AI33Error('Estado da narração AI33 desconhecido; preserve a tarefa e retome depois')
        return data


def checksum(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block)
    return sha.hexdigest()


def paths(audio):
    audio=Path(audio)
    return audio.with_name(audio.stem+'-ai33-tts.json'),audio.with_name(audio.stem+'-ai33.srt')


def load(path):
    if path.is_symlink():raise AI33Error('Registro AI33 inválido')
    if not path.exists():return None
    try:
        if path.stat().st_size>1024*1024:raise ValueError()
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise ValueError()
        return data
    except (ValueError,OSError):raise AI33Error('Registro AI33 inválido; preserve o arquivo para revisão') from None


def save(path,data):
    if path.is_symlink():raise AI33Error('Registro AI33 inválido')
    path.parent.mkdir(parents=True,exist_ok=True)
    write_bytes_atomic(path,json.dumps(data,ensure_ascii=False,indent=2).encode())


def download(url,target,limit):
    # Fresh unauthenticated requests. Validate every redirect; never forward the API key.
    for redirect in range(4):
        try:_public_https(url)
        except AI33Error:raise AI33Error('URL de áudio AI33 precisa ser HTTPS público') from None
        try:
            with requests.get(url,stream=True,timeout=(15,90),allow_redirects=False) as response:
                if response.status_code in {301,302,303,307,308}:
                    location=response.headers.get('Location')
                    if redirect==3 or not location:raise AI33Error('Redirecionamento do áudio AI33 não confirmado')
                    url=urljoin(url,location);continue
                if response.status_code!=200:raise AI33Error('Download AI33 indisponível; retome o mesmo projeto sem reenviar texto')
                size=0
                with Path(target).open('wb') as output:
                    for chunk in response.iter_content(65536):
                        size+=len(chunk)
                        if size>limit:raise AI33Error('Arquivo AI33 excede o limite de download')
                        output.write(chunk)
                if not size:raise AI33Error('AI33 retornou arquivo vazio')
                return
        except requests.RequestException:raise AI33Error('Download AI33 interrompido; retome a tarefa salva') from None
    raise AI33Error('Download AI33 não confirmado')


def srt_content(raw,duration):
    try:text=raw.decode('utf-8-sig').replace('\r\n','\n').strip()
    except UnicodeError:raise AI33Error('Transcrição AI33 não está em UTF-8') from None
    if not text or '\x00' in text:raise AI33Error('Transcrição AI33 vazia ou inválida')
    blocks=re.split(r'\n\s*\n',text);previous=-1
    if len(blocks)>20000:raise AI33Error('Transcrição AI33 excede o limite de segmentos')
    for block in blocks:
        lines=block.splitlines()
        if len(lines)<3 or not lines[0].strip().isdigit():raise AI33Error('Transcrição AI33 não contém SRT válido')
        match=re.fullmatch(r'(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})',lines[1].strip())
        if not match:raise AI33Error('Temporização AI33 inválida')
        values=list(map(int,match.groups()))
        if any(values[i]>=60 for i in (1,2,5,6)):raise AI33Error('Temporização AI33 inválida')
        start=values[0]*3600+values[1]*60+values[2]+values[3]/1000
        end=values[4]*3600+values[5]*60+values[6]+values[7]/1000
        if start<previous or end<=start or end>duration+1 or not ''.join(lines[2:]).strip():raise AI33Error('Transcrição AI33 diverge da duração do áudio')
        previous=start
    return (text+'\n').encode()


def transcript_for(audio,timing=None):
    audio=Path(audio);state_path,caption=paths(audio);state=load(state_path)
    if not state and timing is not None and getattr(timing,'ai33_audio_source',None):
        original=Path(timing.ai33_audio_source)
        source_state,caption=paths(original);state=load(source_state)
        if not state or checksum(original)!=checksum(audio):return None
    if not state or state.get('phase')!='completed' or not state.get('srt_sha256'):return None
    if checksum(audio)!=state.get('audio_sha256') or caption.is_symlink() or not caption.is_file() or checksum(caption)!=state['srt_sha256']:
        raise AI33Error('Áudio ou transcrição AI33 mudou após a geração')
    return srt_content(caption.read_bytes(),state['duration'])


def adopt_preview(audio,timing):
    original=getattr(timing,'ai33_audio_source',None)
    if not original:return
    source_state,_=paths(original);state=load(source_state)
    if not state or checksum(audio)!=state.get('audio_sha256'):raise AI33Error('Prévia AI33 não corresponde ao áudio salvo')
    caption=transcript_for(audio,timing)
    state_path,srt_path=paths(audio)
    if caption:write_bytes_atomic(srt_path,caption)
    save(state_path,state)
    timing.ai33_audio_source=str(audio)


def synthesize(text,identity,speed,audio,volume=1.,*,client=None,settings=None,wait_seconds=None,poll_seconds=8):
    from app.config import config
    from app.services import voice,generation_progress
    settings=config.app if settings is None else settings
    identity=voice_id(identity);audio=Path(audio)
    if not isinstance(text,str) or not text.strip() or len(text)>1_000_000:raise AI33Error('Roteiro AI33 deve ter de 1 a 1.000.000 caracteres')
    if isinstance(speed,bool) or not isinstance(speed,(int,float)) or not math.isfinite(speed) or not .5<=speed<=1.5:raise AI33Error('AI33 aceita velocidade entre 0,5 e 1,5')
    if not isinstance(volume,(int,float)) or not math.isfinite(volume) or not 0<volume<=5:raise AI33Error('Volume AI33 inválido')
    wait_seconds=wait_seconds if wait_seconds is not None else float(settings.get('ai33_tts_wait_minutes',30))*60
    if not math.isfinite(wait_seconds) or not 0<=wait_seconds<=7200:raise AI33Error('Prazo da narração AI33 inválido')
    if audio.is_symlink():raise AI33Error('Saída de áudio AI33 inválida')
    audio.parent.mkdir(parents=True,exist_ok=True)
    state_path,caption_path=paths(audio)
    identity_hash=hashlib.sha256(json.dumps([text,identity,float(speed),float(volume),'transcript-v1'],ensure_ascii=False).encode()).hexdigest()
    with FileLock(str(state_path)+'.lock',timeout=2):
        state=load(state_path)
        if state and state.get('identity')!=identity_hash:raise AI33Error('Roteiro, voz ou velocidade mudou; use um novo projeto, sem sobrescrever a tarefa paga')
        if state and state.get('phase')=='completed' and audio.is_file():
            if checksum(audio)!=state.get('audio_sha256'):raise AI33Error('Áudio AI33 salvo foi alterado; preserve a tarefa antes de retomar')
            return result(audio,state)
        client=client or SpeechClient(api_key(settings))
        if not state:
            try:maximum=int(settings.get('ai33_tts_max_characters',50000))
            except (TypeError,ValueError):raise AI33Error('Configure um teto local de caracteres AI33 válido') from None
            if not 100<=maximum<=1_000_000 or len(text)>maximum:
                raise AI33Error('O roteiro excede o teto local de caracteres AI33; ajuste o limite antes de autorizar a geração')
            state={'version':1,'identity':identity_hash,'voice_id':identity,'speed':float(speed),
                'characters':len(text),'phase':'submitting'}
            save(state_path,state)  # Persist ambiguity before the one paid POST.
            try:remote=client.create(text,identity,float(speed))
            except Exception:
                state['phase']='unconfirmed';save(state_path,state)
                raise AI33Error('AI33 não confirmou o envio. Confira o painel; esta solicitação não será reenviada automaticamente') from None
            state.update(task_id=remote,phase='processing');save(state_path,state)
        elif not state.get('task_id'):
            raise AI33Error('Envio AI33 anterior sem ID confirmado. Revise no painel antes de iniciar outra solicitação')
        if state.get('retry_after',0)>time.time():raise AI33Error('AI33 pediu espera; retome este projeto após o prazo, sem reenviar texto')
        deadline=time.monotonic()+wait_seconds
        while True:
            try:data=client.speech_task(state['task_id'])
            except _TransientError as exc:
                state.update(phase='processing',retry_after=time.time()+max(8,exc.retry_after));save(state_path,state)
                raise AI33Error('Consulta AI33 temporariamente indisponível; ID salvo, retome o mesmo projeto sem reenviar') from None
            generation_progress.remote('ai33_tts',state['task_id'],{'doing':'processing','done':'completed','error':'error'}[data['status']],progress=data.get('progress'))
            if data['status']=='error':
                state['phase']='remote_error';save(state_path,state)
                raise AI33Error('A tarefa de voz falhou na AI33. Confira o painel e o saldo; o roteiro não será reenviado automaticamente')
            if data['status']=='done':break
            if time.monotonic()>=deadline:
                state['phase']='processing';save(state_path,state)
                raise AI33Error('AI33 ainda está gerando a voz. O ID foi salvo; retome o mesmo projeto para consultar')
            time.sleep(min(max(1,poll_seconds),max(0,deadline-time.monotonic())))
        metadata=data.get('metadata') or {};url=metadata.get('audio_url') or data.get('output_uri')
        if not url:raise AI33Error('AI33 concluiu sem URL de áudio utilizável; preserve o ID e confira o painel')
        temp=None;converted=None
        try:
            with tempfile.NamedTemporaryFile(dir=audio.parent,suffix='.audio',delete=False) as f:temp=Path(f.name)
            with tempfile.NamedTemporaryFile(dir=audio.parent,suffix='.mp3',delete=False) as f:converted=Path(f.name)
            download(url,temp,200*1024*1024)
            # Protocol whitelist excludes playlists or nested network fetches in media.
            cmd=[utils.get_ffmpeg_binary(),'-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(temp),
                '-vn','-af','volume='+str(float(volume)),'-codec:a','libmp3lame','-b:a','192k','-y',str(converted)]
            process=subprocess.run(cmd,capture_output=True,timeout=600,check=False)
            if process.returncode:raise AI33Error('Áudio AI33 inválido; nenhuma nova geração foi solicitada')
            voice._validate_remote_tts_audio(str(converted))
            duration=voice.get_audio_duration(str(converted))
            if not math.isfinite(duration) or duration<=0:raise AI33Error('Áudio AI33 sem duração válida')
            state.pop('srt_sha256',None)
            srt_url=metadata.get('srt_url')
            if srt_url:
                try:
                    download(srt_url,temp,2*1024*1024)
                    content=srt_content(temp.read_bytes(),duration)
                    write_bytes_atomic(caption_path,content);state['srt_sha256']=checksum(caption_path)
                except AI33Error:state['transcript_status']='unavailable_or_invalid'
            else:state['transcript_status']='not_available'
            os.replace(converted,audio)
            state.update(phase='completed',audio_sha256=checksum(audio),duration=duration,bytes=audio.stat().st_size)
            cost=data.get('credit_cost')
            if isinstance(cost,(int,float)) and not isinstance(cost,bool) and math.isfinite(cost) and cost>=0:state['actual_credits']=cost
            save(state_path,state)
            return result(audio,state)
        except (OSError,subprocess.TimeoutExpired,ValueError):raise AI33Error('Não foi possível validar o áudio AI33; ID preservado para retomada sem nova cobrança de geração') from None
        finally:
            if temp:temp.unlink(missing_ok=True)
            if converted:converted.unlink(missing_ok=True)


def result(audio,state):
    from app.services import voice
    from edge_tts import SubMaker
    maker=voice.ensure_legacy_submaker_fields(SubMaker())
    maker.duration=float(state['duration']);maker.ai33_audio_source=str(audio)
    # Actual captions are handled by task.generate_subtitle; do not fabricate word timings.
    return maker
