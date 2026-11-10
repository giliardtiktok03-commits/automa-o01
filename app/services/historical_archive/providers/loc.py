from ..contracts import ArchiveCandidate
from .common import text,media,upgrade_url


class LOCProvider:
    name='loc'
    def __init__(self,transport):self.transport=transport
    def health_check(self):
        self.transport.json(self.name,'https://www.loc.gov/search/',params={'fo':'json','q':'photograph','c':1})
        return {'status':'available'}
    def search(self,query,media_types,limit):
        data=self.transport.json(self.name,'https://www.loc.gov/search/',params={'fo':'json','q':query,'c':limit})
        result=[]
        for summary in data.get('results',[])[:limit]:
            source=upgrade_url(summary.get('id') or summary.get('url') or '')
            if not source.startswith(('https://www.loc.gov/item/','https://www.loc.gov/pictures/item/')):continue
            detail=self.transport.json(self.name,source,params={'fo':'json'})
            record=detail.get('item') or summary
            kind=media(record.get('original_format') or summary.get('original_format') or record.get('format'))
            if kind not in media_types:continue
            files=[]
            for resource in detail.get('resources',[]):
                for group in resource.get('files',[]):
                    files.extend(group if isinstance(group,list) else [group])
            acceptable=[]
            for f in files:
                if not isinstance(f,dict):continue
                mimetype=f.get('mimetype','')
                if mimetype in ('image/jpeg','image/png','image/webp','application/pdf','video/mp4') and f.get('url'):
                    acceptable.append(f)
            best=max(acceptable,key=lambda f:int(f.get('width') or 0),default={})
            urls=record.get('image_url') or summary.get('image_url') or []
            if isinstance(urls,str):urls=[urls]
            rights=text(record.get('rights_advisory') or record.get('rights') or detail.get('rights_and_access'))
            result.append(ArchiveCandidate(provider=self.name,record_id=source,title=text(record.get('title') or summary.get('title')),
                description=text(record.get('description')),date_created=text(record.get('date') or summary.get('date')),
                creator=text(record.get('contributor')),institution='Library of Congress',
                media_type=kind,thumbnail_url=upgrade_url(urls[0]) if urls else '',source_url=source,
                download_url=upgrade_url(best.get('url') or (urls[-1] if urls else '')),rights_statement=rights,
                license_url='',attribution='; '.join(filter(None,[text(record.get('title')),text(record.get('contributor')),'Library of Congress',source])),
                metadata={'record':record,'search_result':summary,'response':detail,'resources':detail.get('resources',[]),'width':best.get('width',0),'authenticity':'archive_record_not_ai'}))
        return result
