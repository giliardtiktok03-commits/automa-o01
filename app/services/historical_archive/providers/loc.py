"""Single LOC connector backed by public Metadata, IIIF Image and OCR Text services."""
from ..contracts import ArchiveCandidate,ArchiveError
from ..rights import assess
from .common import text,media,upgrade_url
from .loc_services import LOCMetadataService,LOCImageService,LOCTextService


class LOCProvider:
    name='loc'
    def __init__(self,transport):
        self.transport=transport
        self.metadata_service=LOCMetadataService(transport)
        self.image_service=LOCImageService(transport)
        self.text_service=LOCTextService(transport)

    def health_check(self):
        self.metadata_service.search('photograph',1)
        return {'status':'available','authentication':'public_without_key',
                'services':{'metadata':'available','images':'discovered_per_record','text':'discovered_per_record'}}

    def search(self,query,media_types,limit):
        data=self.metadata_service.search(query,limit)
        result=[]
        for summary in data.get('results',[])[:limit]:
            source=upgrade_url(summary.get('id') or summary.get('url') or '')
            if not source.startswith(('https://www.loc.gov/item/','https://www.loc.gov/pictures/item/','https://www.loc.gov/resource/')):
                self.transport.record('loc_json','record_filter','skipped',reason='Resultado é coleção/página ou URL não suportada, não um registro de material')
                continue
            detail=self.metadata_service.record(source)
            record=detail.get('item') or summary
            kind=media(record.get('original_format') or summary.get('original_format') or record.get('format'))
            if kind not in media_types:
                self.transport.record('loc_json','record_filter','skipped',media_type=kind,reason='Tipo de material não está habilitado')
                continue
            files=[]
            resources=detail.get('resources',[])
            if isinstance(detail.get('resource'),dict):resources=resources+[detail['resource']]
            for resource in resources:
                for group in resource.get('files',[]):
                    files.extend(group if isinstance(group,list) else [group])
            # Newspaper resource endpoints also expose a page array of concrete file variants.
            if isinstance(detail.get('page'),list):files.extend(f for f in detail['page'] if isinstance(f,dict))
            acceptable=[]
            for f in files:
                if isinstance(f,dict) and f.get('url') and f.get('mimetype','') in ('image/jpeg','image/png','image/webp','application/pdf','video/mp4'):
                    acceptable.append(f)
            best=max(acceptable,key=lambda f:int(f.get('width') or 0),default={})
            urls=record.get('image_url') or summary.get('image_url') or []
            if isinstance(urls,str):urls=[urls]
            rights=text(record.get('rights_advisory') or record.get('rights') or detail.get('rights_and_access'))
            candidate=ArchiveCandidate(provider=self.name,record_id=source,title=text(record.get('title') or summary.get('title')),
                description=text(record.get('description')),date_created=text(record.get('date') or summary.get('date')),
                creator=text(record.get('contributor')),institution='Library of Congress',
                media_type=kind,thumbnail_url=upgrade_url(urls[0]) if urls else '',source_url=source,
                download_url=upgrade_url(best.get('url') or (urls[-1] if urls else '')),rights_statement=rights,
                attribution='; '.join(filter(None,[text(record.get('title')),text(record.get('contributor')),'Library of Congress',source])),
                metadata={'record':record,'search_result':summary,'response':detail,'resources':resources,'width':best.get('width',0),
                          'authenticity':'archive_record_not_ai','loc_services':{'metadata':{'status':'available','format':'json'},
                          'images':{'status':'not_available'},'text':{'status':'not_available'}}})
            # Pixel/OCR retrieval never grants rights. Uncertain items still skip automatically.
            rights_status,rights_reason=assess(candidate)
            self.transport.record('loc_json','candidate_rights',rights_status,record=source,classification=rights_status,reason=rights_reason)
            if rights_status=='rights_cleared':
                if kind in {'photograph','document','map'}:
                    try:
                        image=self.image_service.prepare(detail)
                        candidate.metadata['loc_services']['images']=image
                        if image.get('image_url'):
                            candidate.metadata['original_download_url']=candidate.download_url
                            candidate.download_url=image['image_url']
                            candidate.metadata['width']=image['output_width']
                            if self.image_service.settings.loc_diagnostic_probe:
                                image['download_probe']=self.image_service.probe_image(image['image_url'])
                    except Exception as exc:
                        self.transport.record('loc_image','image_info','failed',reason=str(exc) if isinstance(exc,ArchiveError) else 'Falha ao consultar/preparar IIIF')
                        candidate.metadata['loc_services']['images']={'status':'unavailable','error':str(exc) if isinstance(exc,ArchiveError) else 'IIIF indisponível'}
                if kind in {'document','map'}:
                    ocr=self.text_service.extract(detail)
                    candidate.metadata['loc_services']['text']=ocr
                    if ocr['text']:candidate.description+='\nOCR (source data): '+ocr['text'][:4000]
                else:
                    self.transport.record('loc_text','ocr_extraction','not_available',reason='Registro não é documento/mapa com extração OCR aplicável')
            else:
                candidate.metadata['loc_services']['images']['status']='skipped_uncertain_rights'
                candidate.metadata['loc_services']['text']['status']='skipped_uncertain_rights'
                self.transport.record('loc_image','image_info','skipped',reason='Direitos incertos/restritos: imagem não recuperada')
                self.transport.record('loc_text','ocr_extraction','skipped',reason='Direitos incertos/restritos: OCR não recuperado')
            if not candidate.download_url:self.transport.record('loc_image','image_availability','not_available',reason='Registro sem URL utilizável de imagem/arquivo original')
            result.append(candidate)
        return result
