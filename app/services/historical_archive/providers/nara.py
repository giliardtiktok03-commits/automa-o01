from ..contracts import ArchiveCandidate,ArchiveError
from .common import text,media,upgrade_url


class NARAProvider:
    name='nara'
    endpoint='https://catalog.archives.gov/api/v2/records/search'
    def __init__(self,transport,key=''):self.transport,self.key=transport,key
    def health_check(self):
        if not self.key:return {'status':'needs_api_key'}
        self.transport.json(self.name,self.endpoint,params={'q':'photograph'},headers={'x-api-key':self.key})
        return {'status':'available'}
    def search(self,query,media_types,limit):
        if not self.key:raise ArchiveError('NARA: Needs API key — configure NARA_API_KEY ou a chave local')
        data=self.transport.json(self.name,self.endpoint,params={'q':query},headers={'x-api-key':self.key})
        body=data.get('body',data)
        hits=body.get('hits',{})
        rows=hits.get('hits',[]) if isinstance(hits,dict) else hits
        if not rows:rows=body.get('records') or body.get('results') or []
        result=[]
        for row in rows[:limit]:
            record=row.get('_source',row).get('record',row.get('_source',row))
            description=record.get('description',{})
            info=next((description[k] for k in ('item','fileUnit','series') if isinstance(description.get(k),dict)),record)
            record_id=str(record.get('naId') or record.get('naid') or info.get('naId') or '')
            if not record_id.isdigit():continue
            objects=record.get('digitalObjects') or info.get('digitalObjects') or []
            if isinstance(objects,dict):objects=objects.get('digitalObject',[])
            if isinstance(objects,dict):objects=[objects]
            rights=text(info.get('useRestriction') or record.get('useRestriction') or info.get('useRestrictions'))
            for obj in objects[:limit]:
                url=obj.get('objectUrl') or obj.get('fileUrl') or obj.get('url') or ''
                kind=media(obj.get('objectType') or obj.get('mimeType') or info.get('typeOfMaterials') or url)
                if kind not in media_types:continue
                source='https://catalog.archives.gov/id/'+record_id
                title=text(info.get('title') or record.get('title'))
                creator=text(info.get('creators') or record.get('creators'))
                result.append(ArchiveCandidate(provider=self.name,record_id=record_id+':'+str(obj.get('objectId') or len(result)),
                    title=title,description=text(info.get('scopeAndContentNote')),date_created=text(info.get('productionDates') or info.get('inclusiveDates')),
                    creator=creator,institution='National Archives and Records Administration',media_type=kind,
                    thumbnail_url=obj.get('thumbnailUrl',''),source_url=source,download_url=upgrade_url(url),rights_statement=rights,
                    attribution='; '.join(filter(None,[title,creator,'National Archives',source])),
                    metadata={'record':record,'digital_object':obj,'authenticity':'archive_record_not_ai'}))
        return result[:limit]
