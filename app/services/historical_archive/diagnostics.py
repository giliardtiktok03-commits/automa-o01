"""Persisted, redacted per-service evidence; HTTP success is not material approval."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse,urlunparse,parse_qsl,urlencode
from filelock import FileLock
from loguru import logger
from app.utils.atomic_files import write_bytes_atomic
from .manifest import now

SERVICES=('loc_json','loc_image','loc_text')


def safe_request(url,params=None):
    parsed=urlparse(str(url))
    allowed={'q','fo','c','format'}
    query=[(k,v[:250] if k in allowed else '[omitted]') for k,v in parse_qsl(parsed.query,keep_blank_values=True)]
    for k,v in (params or {}).items():query.append((str(k),str(v)[:250] if k in allowed else '[omitted]'))
    return urlunparse(parsed._replace(netloc=parsed.hostname or '',query=urlencode(query),fragment=''))


class DiagnosticRecorder:
    def __init__(self,folder,active):self.folder=Path(folder);self.active=active
    @staticmethod
    def empty():
        return {'version':1,'services':{name:{'status':'not_tested','requests':0,'http_statuses':[],
            'reason':'Nenhuma evidência deste serviço nesta execução'} for name in SERVICES},'events':[]}
    def read(self):
        path=self.folder/'diagnostic-report.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else self.empty()
    def record(self,service,stage,status,**fields):
        if not self.active() and not self.folder.exists():return
        event={'at':now(),'service':service,'stage':stage,'status':status,**fields}
        # Call sites pass only safe fields: never headers, credentials, raw exceptions or bodies.
        logger.info('Archive diagnostic: service={} stage={} status={} details={}',service,stage,status,json.dumps(fields,ensure_ascii=False))
        self.folder.mkdir(parents=True,exist_ok=True)
        with FileLock(str(self.folder/'diagnostic-report.lock'),timeout=30):
            data=self.read()
            data['events']=(data['events']+[event])[-3000:]
            data['updated_at']=event['at']
            summary=data['services'].setdefault(service,{'status':'not_tested','requests':0,'http_statuses':[]})
            if stage=='request':
                summary['requests']+=1
                summary['blocked_attempt']=False
            if stage=='http_response':
                code=fields.get('http_status')
                if code is not None:summary['http_statuses']=list(dict.fromkeys(summary['http_statuses']+[code]))
            if status in {'failed','blocked'}:summary['failed_operations']=summary.get('failed_operations',0)+1
            if status=='passed' and stage not in {'request','http_response','cache_hit'}:summary['passed_operations']=summary.get('passed_operations',0)+1
            if status=='blocked':summary['blocked_attempt']=True
            if status in {'failed','blocked'}:summary.update(status='blocked' if summary.get('blocked_attempt') else status,reason=fields.get('reason',stage))
            elif status=='passed' and stage not in {'request','http_response','cache_hit'}:
                summary.update(status='passed',reason=fields.get('reason',stage),blocked_attempt=False)
            elif status in {'not_available','skipped'} and summary['status']=='not_tested':summary['reason']=fields.get('reason',stage)
            if stage=='search_results':
                summary['search_results']=fields.get('count',0)
                summary['search_results_total']=summary.get('search_results_total',0)+fields.get('count',0)
                summary['availability']='results' if fields.get('count') else 'no_results'
            if stage in {'image_info','image_download','ocr_extraction','rights','selection'}:
                summary[stage+'_status']=status
            if fields.get('reason'):summary['last_reason']=fields['reason']
            write_bytes_atomic(self.folder/'diagnostic-report.json',json.dumps(data,ensure_ascii=False,indent=2).encode())
            lines=['# Historical Archive Finder — diagnostic','',
                   'HTTP status, semantic service status and rights are separate. Untested does not mean passed.','']
            for name,entry in data['services'].items():
                lines.append(f"- {name}: {entry['status']} | requests={entry['requests']} | HTTP={entry['http_statuses']} | {entry.get('reason','')}")
            write_bytes_atomic(self.folder/'diagnostic-report.md','\n'.join(lines).encode())
