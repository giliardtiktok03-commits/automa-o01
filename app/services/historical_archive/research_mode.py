"""Standalone historical research, before script/audio/subtitle/material generation."""
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import threading
from pathlib import Path
from loguru import logger
from app.services import state as sm
from app.models import const
from . import settings
from .contracts import ArchiveError,ArchiveDisabled
from .service import HistoricalArchiveService

_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='loc-diagnostic')
_jobs={}
_lock=threading.Lock()


def requested(params):
    return getattr(params,'video_source','')=='historical_research' or (settings.enabled() and settings.load().mode=='historical_research_only')


def run(task_id,params,*,loc_only=False):
    if not settings.enabled():raise ArchiveDisabled('Ative o Historical Archive Finder para testar os serviços')
    def effective():
        values=dict(settings.mapping())
        values.update(historical_archive_mode='historical_research_only',historical_archive_llm_queries=False,historical_archive_cache_ttl_hours=0,
                      historical_archive_loc_diagnostic_probe=True,historical_archive_loc_image_max_dimension=512)
        if loc_only:values.update(historical_archive_loc_enabled=True,historical_archive_nara_enabled=False,historical_archive_wikimedia_enabled=False)
        return values
    service=HistoricalArchiveService(task_id,settings_getter=effective)
    query=str(params.video_subject or params.video_script or '').strip()
    if not query:raise ArchiveError('Informe uma consulta/tema para o diagnóstico histórico')
    sm.state.update_task(task_id,state=const.TASK_STATE_PROCESSING,progress=0,historical_research_only=True,error=None,failed_stage=None)
    logger.info('Historical research only: task_id={} — no video, audio, subtitles, stock or AI generation',task_id)
    service.report('research','research_start','started',reason='Pesquisa independente: sem vídeo, áudio, bancos ou geradores IA')
    scene={'id':1,'text':params.video_script or query,'search_query':query}
    entry=service.search_scene(scene,refresh=True)
    if not service.active():
        service.report('research','research_end','skipped',reason='Pesquisa cancelada/desativada')
    report=service.diagnostic().read()
    services={name:report['services'].get(name,{}) for name in ('loc_json','loc_image','loc_text')}
    outcome='all_services_passed' if all(v.get('status')=='passed' for v in services.values()) else 'completed_with_failures' if any(v.get('status') in {'failed','blocked'} for v in services.values()) else 'incomplete_services_not_tested'
    result={'outcome':outcome,'task_id':task_id,'historical_research_only':True,'diagnostic_report':str(service.folder/'diagnostic-report.json'),
            'candidates':len((entry or {}).get('candidates',[])),'api_results':report['services']}
    sm.state.update_task(task_id,state=const.TASK_STATE_COMPLETE,progress=100,**{k:v for k,v in result.items() if k!='task_id'})
    return result


def submit_loc(query):
    from app.models.schema import VideoParams
    if not settings.enabled():raise ArchiveDisabled('Ative o módulo antes de testar')
    if not query.strip():raise ArchiveError('Informe a consulta de teste')
    task_id='loc-diagnostic-'+uuid4().hex
    params=VideoParams(video_subject=query,video_source='historical_research')
    with _lock:
        if any(not future.done() for future in _jobs.values()):raise ArchiveError('Já há um teste LOC em andamento; atualize o resultado')
        _jobs[task_id]=_pool.submit(run,task_id,params,loc_only=True)
    return task_id


def status(task_id):
    with _lock:future=_jobs.get(task_id)
    if not future:return 'saved'
    if not future.done():return 'running'
    return 'failed' if future.exception() else 'completed'


def latest_probe():
    from app.utils import utils
    root=Path(utils.storage_dir())/'tasks'
    entries=[]
    for report in root.glob('loc-diagnostic-*/historical_archive/diagnostic-report.json'):
        try:entries.append((report.stat().st_mtime_ns,report.parent.parent.name))
        except OSError:continue
    return max(entries)[1] if entries else None
