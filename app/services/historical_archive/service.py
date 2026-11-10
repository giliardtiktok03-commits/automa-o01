"""Global coordinator: OFF is a hard network/download gate, including active jobs."""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse,urlunparse
from filelock import FileLock

from app.services import generation_progress
from app.services import state as sm
from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic
from . import settings as global_settings
from .contracts import ArchiveCandidate,ArchiveError,ArchiveDisabled,ArchivePending
from .network import Transport
from .providers import providers
from .query_builder import build
from .ranker import rank
from .rights import assess
from . import manifest
from .downloader import download,local,checksum


def paths(task_id):
    if not re.fullmatch(r'[\w-]{1,80}(?:/chapters/\d{3})?',task_id,re.ASCII):raise ArchiveError('ID de projeto inválido')
    base_id=task_id.split('/')[0]
    root=(Path(utils.storage_dir())/'tasks').resolve()
    directory=(root/base_id).resolve()
    if not directory.is_relative_to(root):raise ArchiveError('Projeto fora da pasta tasks')
    suffix=task_id.split('/chapters/')[-1] if '/chapters/' in task_id else ''
    folder=(directory/'historical_archive').resolve()
    if not folder.is_relative_to(directory):raise ArchiveError('Pasta histórica fora do projeto')
    return folder,suffix


class HistoricalArchiveService:
    def __init__(self,task_id,settings_getter=None,provider_factory=None,transport=None):
        self.task_id=task_id
        self.get_settings=settings_getter or global_settings.mapping
        self.provider_factory=provider_factory or providers
        self._transport=transport
        self._folder=None
        self.cancelled=False

    def settings(self):return global_settings.load(self.get_settings())
    def active(self):return not self.cancelled and self.settings().enabled
    def cancel(self):self.cancelled=True
    @property
    def folder(self):
        if self._folder is None:self._folder,self.chapter=paths(self.task_id)
        return self._folder
    def key(self,scene_id):
        _=self.folder
        if not isinstance(scene_id,int) or not 1<=scene_id<=10000:raise ArchiveError('Cena inválida')
        return f'chapter_{self.chapter}_scene_{scene_id:03d}' if self.chapter else f'scene_{scene_id:03d}'
    def transport(self):
        return self._transport or Transport(Path(utils.storage_dir())/'historical_archive_cache',self.settings(),self.active)
    def credentials(self):
        return {'nara_api_key':str(self.get_settings().get('historical_archive_nara_api_key') or os.environ.get('NARA_API_KEY') or '').strip()}
    def status(self,phase,**fields):
        generation_progress.stage('historical_archive')
        try:sm.state.patch_task(self.task_id,historical_archive_status=phase,**fields)
        except Exception:pass
    def snapshot(self):return manifest.read(self.folder)
    def health_check(self):
        if not self.active():return {'status':'disabled'}
        result={}
        for provider in self.provider_factory(self.transport(),self.settings(),self.credentials()):
            if not self.active():break
            try:result[provider.name]=provider.health_check()
            except Exception as exc:result[provider.name]={'status':'unavailable','error':self.error(exc)}
        return result
    @staticmethod
    def error(exc):
        return str(exc)[:300] if isinstance(exc,ArchiveError) else type(exc).__name__+' — consulta indisponível; outros providers continuam'

    def search_scene(self,scene,terms=None,*,refresh=False):
        if not self.active():return None
        settings=self.settings()
        folder=self.folder
        folder.mkdir(parents=True,exist_ok=True)
        with FileLock(str(folder/'manifest.lock'),timeout=60):
            if not self.active():return None
            data=manifest.read(folder)
            key=self.key(scene['id'])
            query=build(scene,settings,terms)
            signature=hashlib.sha256(json.dumps([query,settings.model_dump()],sort_keys=True).encode()).hexdigest()
            old=data['scenes'].get(key)
            # Previously approved/downloaded assets are preserved. Search results are stable on resume.
            if old and old.get('signature')==signature and not refresh:
                from datetime import datetime,timezone
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(old['searched_at'])).total_seconds()
                if age<settings.cache_ttl_hours*3600:return old
            if old and any(c.get('state')=='downloaded' for c in old.get('candidates',[])):return old
            entry={'scene_id':scene['id'],'text':str(scene.get('text','')),'query':query,'signature':signature,
                   'searched_at':manifest.now(),'candidates':[],'status':'searching'}
            data['scenes'][key]=entry
            self.status('Searching archives...')
            seen=set()
            for provider in self.provider_factory(self.transport(),settings,self.credentials()):
                for q in query['queries']:
                    if not self.active():
                        entry['status']='cancelled';manifest.save(folder,data);return entry
                    try:
                        candidates=provider.search(q,query['media_types'],settings.candidates_per_scene)
                        data['providers'][provider.name]={'status':'available','checked_at':manifest.now()}
                    except Exception as exc:
                        data['providers'][provider.name]={'status':'unavailable','error':self.error(exc),'checked_at':manifest.now()}
                        break
                    for candidate in candidates:
                        parsed=urlparse(candidate.download_url)
                        canonical=urlunparse(parsed._replace(query='',fragment=''))
                        identity=candidate.provider+':'+candidate.record_id
                        if identity in seen or (canonical and canonical in seen):continue
                        seen.update([identity,canonical])
                        status,reason=assess(candidate)
                        score,explanation=rank(candidate,query,status)
                        if candidate.metadata.get('ai_generated'):
                            status,reason='needs_review','Item sinalizado como IA; não tratar como arquivo histórico autêntico'
                        cid=hashlib.sha256(identity.encode()).hexdigest()[:24]
                        entry['candidates'].append({'id':cid,'candidate':candidate.to_dict(),'state':'skipped_unknown_rights' if status=='needs_review' else status,'rights_status':status,
                            'rights_reason':reason,'score':score,'score_explanation':explanation,'used':False})
                # Provider order defines tie preference, while all selected sources can contribute.
            # Do not let a high-scoring but unusable record crowd out a legally usable match.
            def eligible(item):
                relevance=item['score_explanation']
                return item['rights_status']=='rights_cleared' and item['score']>=settings.min_score and relevance.get('event',0)>=.15 and not relevance.get('conflicting_context')
            entry['candidates'].sort(key=lambda c:(eligible(c),c['score']),reverse=True)
            entry['candidates']=entry['candidates'][:settings.candidates_per_scene]
            if self.active():
                for item in entry['candidates']:
                    ocr=item['candidate']['metadata'].get('loc_services',{}).get('text',{})
                    if ocr.get('text'):
                        target=folder/key/'candidates'/(item['id']+'.ocr.txt')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        write_bytes_atomic(target,ocr['text'].encode('utf-8'))
                        item['ocr_file']=str(target.relative_to(folder))
            entry['status']='completed'
            manifest.save(folder,data)
            self.status('Search completed',historical_archive_candidates=len(entry['candidates']),
                        historical_archive_skipped_rights=sum(c['rights_status']!='rights_cleared' for c in entry['candidates']),
                        historical_archive_approved=sum(c['state'] in {'approved','downloaded','rights_cleared'} for c in entry['candidates']))
            return entry

    def select(self,scene,terms=None,*,candidate_id=None,use_saved=False):
        if not self.active():return None,None
        entry=self.snapshot()['scenes'].get(self.key(scene['id'])) if use_saved else self.search_scene(scene,terms)
        if not entry or not self.active():return None,None
        settings=self.settings()
        if settings.mode=='historical_research_only':return None,None
        key=self.key(scene['id'])
        with FileLock(str(self.folder/'manifest.lock'),timeout=60):
            data=manifest.read(self.folder)
            entry=data['scenes'][key]
            used_elsewhere={c.get('sha256') for scene_key,s in data['scenes'].items() if scene_key!=key for c in s.get('candidates',[]) if c.get('used')}
            used_records={(c['candidate']['provider'],c['candidate']['record_id']) for scene_key,s in data['scenes'].items() if scene_key!=key for c in s.get('candidates',[]) if c.get('used')}
            for item in entry['candidates']:
                if (item['candidate']['provider'],item['candidate']['record_id']) in used_records:continue
                if candidate_id and item['id']!=candidate_id:continue
                if item.get('sha256') in used_elsewhere or item['state']=='failed':continue
                explicit=use_saved and candidate_id==item['id'] and item['rights_status']=='rights_cleared' and item['state']!='rejected'
                allowed=item['rights_status']=='rights_cleared' and (explicit or item['state']=='downloaded' or settings.auto_download_rights_cleared) and item['state']!='rejected'
                relevance=item.get('score_explanation',{})
                if not allowed or item['score']<settings.min_score or relevance.get('event',0)<.15 or relevance.get('conflicting_context'):continue
                if item.get('downloaded_file'):
                    path=local(self.folder,item['downloaded_file'])
                    if not path.is_file() or checksum(path)!=item.get('sha256'):
                        item['state']='failed';item['error']='Arquivo alterado ou ausente; revise antes de baixar novamente';continue
                else:
                    if len(data['downloads'])>=settings.max_downloads_per_video:break
                    if not self.active():break
                    candidate=ArchiveCandidate(**item['candidate'])
                    try:
                        path,digest=download(candidate,self.folder/key/'approved',self.transport())
                    except Exception as exc:
                        item.update(state='failed',error=self.error(exc));continue
                    if digest in data['downloads']:
                        shared=local(self.folder,data['downloads'][digest])
                        if path!=shared and shared.exists():path.unlink();path=shared
                    data['downloads'][digest]=str(path.relative_to(self.folder))
                    item.update(state='downloaded',downloaded_file=str(path.relative_to(self.folder)),sha256=digest,downloaded_at=manifest.now())
                if item.get('sha256') in used_elsewhere:continue
                if not self.active():
                    manifest.save(self.folder,data)
                    return None,None
                # A media item is not "used" until rendering actually succeeded.
                manifest.save(self.folder,data)
                return str(path), {'provider':'historical_archive','archive_provider':item['candidate']['provider'],
                    'archive_candidate_id':item['id'],'archive_scene_key':key,'source_identity':'archive:'+item['sha256'],
                    'source_digest':item['sha256'],'source_start':0,'source_end':1,'illustration':False,
                    'source_url':item['candidate']['source_url'],'rights_status':item['rights_status'],'local_file':str(path)}
            manifest.save(self.folder,data)
        return None,None

    def download_item(self,scene_id,candidate_id):
        scene=self.snapshot()['scenes'][self.key(scene_id)]
        return self.select({'id':scene_id,'text':scene['text']},candidate_id=candidate_id,use_saved=True)

    def mark_used(self,provenance):
        if not provenance or provenance.get('provider')!='historical_archive':return
        with FileLock(str(self.folder/'manifest.lock'),timeout=60):
            data=manifest.read(self.folder)
            for item in data['scenes'].get(provenance['archive_scene_key'],{}).get('candidates',[]):
                if item['id']==provenance['archive_candidate_id']:item['used']=True
            manifest.save(self.folder,data)
            manifest.credits(self.folder,data)
