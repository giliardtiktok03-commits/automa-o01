"""Explicit local Commons test. Never starts a video job or calls any publisher."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import threading
from uuid import uuid4
from datetime import datetime, timezone

from filelock import FileLock
from app.models.schema import VideoParams
from app.services.historical_archive.contracts import ArchiveError
from app.services.historical_archive.service import HistoricalArchiveService
from app.services.historical_archive.rights import assess
from app.services.historical_archive.downloader import checksum, local
from app.services.historical_archive.providers.wikimedia import WikimediaProvider
from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic

_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='commons-test')
_jobs={}
_guard=threading.Lock()


def folder(task_id):
    if not re.fullmatch(r'commons-test-[a-f0-9]{32}',task_id):raise ArchiveError('ID de teste Commons inválido')
    root=Path(utils.storage_dir())/'tasks'
    target=root/task_id/'historical_archive'
    if (root/task_id).is_symlink() or target.is_symlink():raise ArchiveError('Pasta de teste inválida')
    return target


def save(task_id,data):
    target=folder(task_id);target.mkdir(parents=True,exist_ok=True)
    write_bytes_atomic(target/'commons-test.json',json.dumps(data,ensure_ascii=False,indent=2).encode())


def read(task_id):
    file=folder(task_id)/'commons-test.json'
    return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}


def latest():
    root=Path(utils.storage_dir())/'tasks'
    items=[]
    for p in root.glob('commons-test-*/historical_archive/commons-test.json'):
        if p.parent.is_symlink() or p.parent.parent.is_symlink():continue
        try:items.append((p.stat().st_mtime_ns,p.parent.parent.name))
        except OSError:continue
    return max(items)[1] if items else None


def decision(candidate):
    """Extra restrictions for the independent probe, not a general license manager."""
    from .commons_license import classify
    result=classify(candidate)
    return result['classification'],result['reason']


def render_clip(source,target):
    from app.services import mixed_materials
    params=VideoParams(video_subject='Commons diagnostic',video_aspect='16:9',video_fit_mode='contain',
        image_motion='static',n_threads=2,subtitle_enabled=False,bgm_type='')
    mixed_materials.render(source,target,120,params)
    # Full decode, not just opening the MP4 header. No audio required for a test clip.
    checked=subprocess.run([utils.get_ffmpeg_binary(),'-nostdin','-hide_banner','-v','error','-xerror',
        '-i',str(target),'-map','0:v:0','-f','null','-'],capture_output=True,timeout=120,check=False)
    if checked.returncode:raise ArchiveError('O clipe de teste não pôde ser decodificado')
    from moviepy import VideoFileClip
    with VideoFileClip(str(target),audio=False) as clip:
        duration=float(clip.duration)
        if list(clip.size)!=[1920,1080] or not 3.85<=duration<=4.15:
            raise ArchiveError('Dimensões ou duração do clipe de teste inválidas')
    return {'file':target.name,'sha256':checksum(target),'bytes':target.stat().st_size,
            'duration':duration,'width':1920,'height':1080,'decode_verified':True}


def run(task_id,query,make_clip=True):
    target=folder(task_id);target.mkdir(parents=True,exist_ok=True)
    values={'historical_archive_enabled':True,'historical_archive_loc_enabled':False,
        'historical_archive_nara_enabled':False,'historical_archive_wikimedia_enabled':True,
        'historical_archive_mode':'historical_plus_stock','historical_archive_llm_queries':False,
        'historical_archive_candidates_per_scene':10,'historical_archive_max_downloads_per_video':1,
        'historical_archive_max_retries':0}
    service=HistoricalArchiveService(task_id,settings_getter=lambda:values)
    report={'task_id':task_id,'query':query,'state':'running','stage':'Consultando Commons',
        'checked_at':datetime.now(timezone.utc).isoformat(),
        'published':False,'license_manager_complete':True,'candidates':[]}
    save(task_id,report)
    try:
        with FileLock(str(target/'commons-test.lock'),timeout=0):
            # Retain the exact-query API records even if later editorial selection fails.
            candidates=WikimediaProvider(service.transport()).search(query,['photograph'],10)
            report['candidates']=[{'candidate':c.to_dict(),'classification':decision(c)[0],
                'reason':decision(c)[1],'used_in_test':False} for c in candidates]
            report['stage']='Conferindo metadados';save(task_id,report)
            scene={'id':1,'text':query,'search_query':query}
            entry=service.search_scene(scene)
            eligible={c.record_id for c in candidates if decision(c)[0]=='AUTO_APPROVED'}
            source=provenance=None
            for item in entry['candidates']:
                if item['candidate']['record_id'] not in eligible:continue
                source,provenance=service.select(scene,candidate_id=item['id'],use_saved=True)
                if source:break
            if not source:
                report.update(state='needs_review',stage='Nenhuma fotografia elegível para este teste')
                save(task_id,report);return report
            report['download']={'file':str(Path(source).relative_to(target)), 'sha256':checksum(source)}
            save(task_id,report)
            if make_clip:
                report['stage']='Gerando clipe de 4 segundos';save(task_id,report)
                report['clip']=render_clip(source,target/'commons-test-clip.mp4')
                report['stage']='Vinculando imagem ao clipe';save(task_id,report)
                service.mark_used(provenance,output=target/'commons-test-clip.mp4',params=VideoParams(video_subject=query,video_aspect='16:9',video_fit_mode='contain',image_motion='static'))
                from .commons_credits import bind_final,prepare_description
                report['stage']='Conferindo auditoria e gerando créditos';save(task_id,report)
                binding=bind_final(task_id,target/'commons-test-clip.mp4',[target/'commons-test-clip.mp4'])
                if not binding or not binding.get('bindings'):raise ArchiveError('Nenhuma imagem foi vinculada ao clipe; confira o relatório de revisão')
                report['description_with_credits']=prepare_description(target/'commons-test-clip.mp4','Local Wikimedia Commons integration test.')
                record_id=next(i['candidate']['record_id'] for i in service.snapshot()['scenes']['scene_001']['candidates'] if i['id']==provenance['archive_candidate_id'])
                for row in report['candidates']:
                    row['used_in_test']=row['candidate']['record_id']==record_id
                report['modifications']=['RGB normalization','Fit inside 16:9 canvas with padding','Static 4-second test clip']
            report.update(state='completed',stage='Teste concluído')
    except Exception as exc:
        failed_stage=report.get('stage')
        report.update(state='failed',stage='Teste interrompido',error_stage=failed_stage,error_type=type(exc).__name__,
            error=str(exc) if isinstance(exc,ArchiveError) else 'Falha no teste ('+type(exc).__name__+'); confira o relatório técnico')
        if report.get('clip'):
            from .commons_credits import error_report
            error_report(target,target/'commons-test-clip.mp4',exc)
    save(task_id,report)
    return report


def submit(query,make_clip=True):
    query=query.strip()
    if not query or len(query)>250 or '\x00' in query:raise ArchiveError('Informe uma consulta válida de até 250 caracteres')
    with _guard:
        if any(not future.done() for future in _jobs.values()):raise ArchiveError('Já há um teste Commons em execução')
        task_id='commons-test-'+uuid4().hex
        save(task_id,{'task_id':task_id,'query':query,'state':'queued','stage':'Aguardando início','published':False})
        _jobs[task_id]=_pool.submit(run,task_id,query,make_clip)
    return task_id


def repair_credits(task_id):
    """Reuse the verified saved clip and image. No network or rendering calls."""
    from .commons_credits import bind_final,prepare_description,digest,project_file,error_report
    target=folder(task_id);report=read(task_id)
    try:
        with FileLock(str(target/'commons-test.lock'),timeout=0):
            report.update(state='running',stage='Concluindo créditos do clipe salvo');save(task_id,report)
            clip=artifact(task_id,'commons-test-clip.mp4')
            if report.get('clip',{}).get('sha256')!=digest(clip):
                raise ArchiveError('O clipe salvo mudou; não é seguro gerar créditos automaticamente')
            source=project_file(target,report.get('download',{}).get('file',''))
            if digest(source)!=report.get('download',{}).get('sha256'):
                raise ArchiveError('A imagem salva mudou; restaure o arquivo original antes de concluir os créditos')
            record=bind_final(task_id,clip,[clip])
            if not record or not record.get('bindings'):raise ArchiveError('Não foi possível vincular uma imagem ao clipe salvo')
            report['description_with_credits']=prepare_description(clip,'Local Wikimedia Commons integration test.')
            manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
            ids={i['candidate']['record_id'] for scene in manifest['scenes'].values() for i in scene.get('candidates',[])
                if i.get('used') and i['candidate']['provider']=='wikimedia'}
            for row in report.get('candidates',[]):row['used_in_test']=row['candidate']['record_id'] in ids
            report.update(state='completed',stage='Créditos concluídos sem novo download ou renderização',
                credits_checked_at=datetime.now(timezone.utc).isoformat(),published=False)
            for key in ('error','error_type','error_stage'):report.pop(key,None)
    except Exception as exc:
        reason=error_report(target,target/'commons-test-clip.mp4',exc)
        report.update(state='failed',stage='Não foi possível concluir os créditos',error=reason,
            error_type=type(exc).__name__,error_stage='repair_credits',published=False)
    save(task_id,report)
    return report


def submit_repair(task_id):
    report=read(task_id)
    if not report.get('clip') or not report.get('download'):raise ArchiveError('Este teste ainda não tem clipe e imagem salvos')
    with _guard:
        if any(not future.done() for future in _jobs.values()):raise ArchiveError('Já há um teste Commons em execução')
        report.update(state='queued',stage='Aguardando conclusão dos créditos');save(task_id,report)
        _jobs[task_id]=_pool.submit(repair_credits,task_id)
    return task_id


def artifact(task_id,name):
    if name not in {'commons-test.json','commons-test-clip.mp4','manifest.json','diagnostic-report.json','search_log.json','sources_and_credits.json','sources_and_credits.md','commons-license-audit.json','commons-publication-review.json','historical-image-credits.txt','youtube-description-with-credits.txt'}:
        raise ArchiveError('Arquivo de teste inválido')
    path=local(folder(task_id),name)
    if not path.is_file():raise ArchiveError('Arquivo de teste ainda não existe')
    return path
