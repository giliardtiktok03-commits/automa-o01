import json
import re
from ..contracts import ArchiveCandidate
from .common import text,media


class WikimediaProvider:
    name='wikimedia'
    endpoint='https://commons.wikimedia.org/w/api.php'
    def __init__(self,transport):self.transport=transport
    def health_check(self):
        self.transport.json(self.name,self.endpoint,params={'action':'query','meta':'siteinfo','format':'json'})
        return {'status':'available'}
    def search(self,query,media_types,limit):
        data=self.transport.json(self.name,self.endpoint,params={'action':'query','format':'json','generator':'search',
            'maxlag':5,'gsrsearch':query,'gsrnamespace':6,'gsrlimit':limit,'prop':'imageinfo|categories','cllimit':50,'iiprop':'url|extmetadata|size|mime','iiurlwidth':1000})
        pages=data.get('query',{}).get('pages',{})
        rows=pages.values() if isinstance(pages,dict) else pages
        result=[]
        for page in rows:
            info=(page.get('imageinfo') or [{}])[0]
            ext=info.get('extmetadata',{})
            def val(key):return text((ext.get(key) or {}).get('value',''))
            kind=media(info.get('mime','')+' '+page.get('title','')+' '+val('ObjectName'))
            if kind not in media_types:continue
            artist=val('Artist')
            title=val('ObjectName') or page.get('title','')
            source=info.get('descriptionurl','')
            original=info.get('url','')
            raster_preview=info.get('mime') in {'image/svg+xml','application/pdf','image/vnd.djvu'} and bool(info.get('thumburl'))
            credit='; '.join(filter(None,[title,artist,val('Credit'),val('LicenseShortName'),source]))
            result.append(ArchiveCandidate(provider=self.name,record_id=str(page.get('pageid','')),title=title,
                description=val('ImageDescription'),date_created=val('DateTimeOriginal'),creator=artist,
                institution=val('Institution') or 'Wikimedia Commons',media_type=kind,
                thumbnail_url=info.get('thumburl',''),source_url=source,download_url=info.get('thumburl') if raster_preview else original,
                rights_statement='; '.join(filter(None,[val('LicenseShortName'),val('UsageTerms'),val('Restrictions')])),
                license_url=val('LicenseUrl'),attribution=credit,metadata={'record':page,'width':info.get('width',0),'height':info.get('height',0),
                'download_variant':'API raster preview (first page for documents)' if raster_preview else 'original',
                'original_file_url':original,'authenticity':'repository_record_unverified','ai_generated':bool(re.search(r'ai[- ]generated|midjourney|dall[- ]?e|stable diffusion',json.dumps(page,ensure_ascii=False),re.I))}))
        return result[:limit]
