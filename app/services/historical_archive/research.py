"""Bounded background editorial research; UI remains available to disable/cancel."""
import threading
from concurrent.futures import ThreadPoolExecutor
from .contracts import ArchiveError
from .service import HistoricalArchiveService

_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='archive-research')
_lock=threading.Lock()
_jobs={}


def submit(task_id,scenes,terms=None):
    service=HistoricalArchiveService(task_id)
    if not service.active():raise ArchiveError('Ative a pesquisa histórica primeiro')
    with _lock:
        current=_jobs.get(task_id)
        if current and not current[0].done():raise ArchiveError('Já existe pesquisa para este projeto')
        def run():
            for scene in scenes:
                if not service.active():break
                service.search_scene(scene,terms,refresh=True)
        future=_pool.submit(run)
        _jobs[task_id]=(future,service)


def status(task_id):
    with _lock:job=_jobs.get(task_id)
    if not job:return ''
    future,service=job
    if service.cancelled:return 'Pesquisa cancelada; resultados anteriores preservados'
    if not future.done():return 'Searching archives...'
    return 'Pesquisa interrompida; confira os providers no manifesto' if future.exception() else 'Search completed'


def cancel(task_id):
    with _lock:job=_jobs.get(task_id)
    if job:job[1].cancel()
