"""LOC's three public services. Discover resource links; never invent OCR endpoints."""
import json
import math
import re
import io
from PIL import Image
from urllib.parse import urlparse,urlunparse,unquote
from xml.etree import ElementTree
from html.parser import HTMLParser

from ..contracts import ArchiveSettings,ArchiveError
from ..network import safe_url
from .common import upgrade_url


def resource_urls(value):
    if isinstance(value,dict):
        for nested in value.values():yield from resource_urls(nested)
    elif isinstance(value,list):
        for nested in value:yield from resource_urls(nested)
    elif isinstance(value,str):
        url=upgrade_url(value)
        if url.startswith('https://'):
            parsed=urlparse(url)
            if parsed.hostname and (parsed.hostname=='loc.gov' or parsed.hostname.endswith('.loc.gov')):
                yield url


def service_settings(transport):
    value=getattr(transport,'settings',None)
    return value if isinstance(value,ArchiveSettings) else ArchiveSettings()


class LOCMetadataService:
    """JSON representation of the public JSON/YAML API; no authentication."""
    def __init__(self,transport):self.transport=transport
    def search(self,query,limit):
        try:
            data=self.transport.json('loc_json','https://www.loc.gov/search/',params={'fo':'json','q':query,'c':limit})
            if not isinstance(data,dict) or not isinstance(data.get('results'),list):
                raise ArchiveError('JSON/YAML respondeu sem a lista results; formato inesperado')
            self.transport.record('loc_json','search_results','passed',count=len(data['results']),reason='Pesquisa válida' if data['results'] else 'Pesquisa válida, mas nenhum registro encontrado')
            return data
        except Exception as exc:
            self.transport.record('loc_json','metadata_search','failed',reason=str(exc) if isinstance(exc,ArchiveError) else 'JSON inválido ou falha de transporte')
            raise
    def record(self,url):
        safe_url(url)
        parsed=urlparse(url)
        if parsed.hostname!='www.loc.gov' or not parsed.path.startswith(('/item/','/pictures/item/','/resource/')):
            raise ArchiveError('Registro fora da API pública LOC')
        data=self.transport.json('loc_json',url,params={'fo':'json'})
        if not isinstance(data,dict) or not any(key in data for key in ('item','resource','resources','page')):
            self.transport.record('loc_json','record_metadata','failed',reason='Resposta sem metadados de registro reconhecíveis')
            raise ArchiveError('Metadados LOC sem item/resource; resposta não pode virar material')
        self.transport.record('loc_json','record_metadata','passed',reason='Metadados de registro recebidos')
        return data


class LOCImageService:
    def __init__(self,transport):self.transport=transport;self.settings=service_settings(transport)

    @staticmethod
    def discover(value):
        for url in resource_urls(value):
            parsed=urlparse(url)
            if parsed.hostname!='tile.loc.gov' or not parsed.path.startswith('/image-services/iiif/'):continue
            clean=urlunparse(parsed._replace(query='',fragment=''))
            if clean.endswith('/info.json'):return clean[:-len('/info.json')]
            parts=clean.rsplit('/',4)
            if len(parts)==5 and re.fullmatch(r'[\w-]+\.(?:jpg|jpeg|png|webp)',parts[-1],re.I):return parts[0]
        return ''

    def prepare(self,value):
        base=self.discover(value)
        if not base:
            self.transport.record('loc_image','image_info','not_available',reason='Registro não divulga um link IIIF')
            return {'status':'not_available'}
        info_url=base+'/info.json'
        info=self.transport.json('loc_image',info_url)
        width,height=info.get('width'),info.get('height')
        if any(not isinstance(v,int) or isinstance(v,bool) or v<=0 for v in (width,height)):
            raise ArchiveError('IIIF info.json sem dimensões válidas')
        announced=upgrade_url(info.get('id') or info.get('@id') or base).rstrip('/')
        announced_url,base_url=urlparse(announced),urlparse(base)
        if (announced_url.scheme,announced_url.hostname,unquote(announced_url.path),announced_url.query)!=(base_url.scheme,base_url.hostname,unquote(base_url.path),base_url.query):
            raise ArchiveError('IIIF informa outro identificador; imagem não foi substituída')
        maximum=self.settings.loc_image_max_dimension
        scale=min(1,maximum/width,maximum/height)
        profile_details=next((entry for entry in info.get('profile',[]) if isinstance(entry,dict)),{}) if isinstance(info.get('profile'),list) else {}
        for key,dimension in [('maxWidth',width),('maxHeight',height)]:
            value=info.get(key,profile_details.get(key))
            if isinstance(value,(int,float)) and not isinstance(value,bool) and value>0:scale=min(scale,value/dimension)
        area=info.get('maxArea',profile_details.get('maxArea'))
        if isinstance(area,(int,float)) and not isinstance(area,bool) and area>0:scale=min(scale,math.sqrt(area/(width*height)))
        target_width=max(1,int(width*scale))
        target_height=max(1,int(height*target_width/width))
        profile=json.dumps(info.get('profile',[]))
        supports=json.dumps(info.get('extraFeatures',[]))+' '+profile
        if re.search(r'level[12](?:\b|\.json)',profile) or 'sizeByW' in supports:
            size=str(target_width)+','
        elif max(width,height)<=maximum:
            size='max' if '/image/3/' in json.dumps(info.get('@context','')) else 'full'
        else:
            sizes=[s for s in info.get('sizes',[]) if isinstance(s,dict) and isinstance(s.get('width'),int) and isinstance(s.get('height'),int)
                   and 0<s['width']<=target_width and 0<s['height']<=target_height]
            if not sizes:raise ArchiveError('IIIF não declara redimensionamento compatível; arquivo original mantido como fallback')
            best=max(sizes,key=lambda s:s['width']*s['height'])
            target_width,target_height=best['width'],best['height']
            size=f"{best['width']},{best['height']}"
        self.transport.record('loc_image','image_info','passed',width=width,height=height,output_width=target_width,reason='info.json válido; imagem IIIF disponível')
        return {'status':'available','info_url':info_url,'image_url':base+'/full/'+size+'/0/default.jpg',
                'width':width,'height':height,'output_width':target_width,'output_height':target_height,'region':'full','rotation':0,'max_dimension':maximum,'info':info}

    def probe_image(self,image_url):
        try:
            content=self.transport.get('loc_image',image_url,max_bytes=2*1024*1024)
            with Image.open(io.BytesIO(content)) as image:
                if image.width*image.height>4_000_000:raise ArchiveError('Prévia IIIF excede limite do diagnóstico')
                image.load()
                size=image.size
            self.transport.record('loc_image','image_download','passed',width=size[0],height=size[1],reason='Prévia IIIF recebida e decodificada em memória; sem montagem de vídeo')
            return {'status':'passed','width':size[0],'height':size[1]}
        except Exception as exc:
            self.transport.record('loc_image','image_download','failed',reason=str(exc) if isinstance(exc,ArchiveError) else 'Falha ao receber/decodificar prévia IIIF')
            return {'status':'failed','reason':'Prévia IIIF não recebida/validada'}


class _HOCR(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.ignore=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.ignore+=1
        if tag in ('p','div','br'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.ignore=max(0,self.ignore-1)
    def handle_data(self,data):
        if not self.ignore:self.parts.append(data)


def parse_ocr(raw,max_chars):
    """ALTO/hOCR/plain text and word-coordinate JSON; OCR remains untrusted source data."""
    encoding='utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
    source=raw.decode(encoding,errors='replace').strip()
    if not source:raise ArchiveError('OCR vazio')
    format='text'
    if source.startswith(('{','[')):
        data=json.loads(source)
        if isinstance(data,dict) and data.get('error'):raise ArchiveError('Text Services devolveu erro, não OCR')
        def extract(obj):
            if isinstance(obj,dict):
                for key in ('full_text','fulltext','text','word','CONTENT','content'):
                    if isinstance(obj.get(key),str):return [obj[key]]
                if isinstance(obj.get('words'),dict):return list(obj['words'])
                return [v for child in obj.values() for v in extract(child)]
            if isinstance(obj,list):return [v for child in obj for v in (extract(child) if not isinstance(child,str) else [child])]
            return []
        source=' '.join(extract(data));format='word_coordinates_json'
    elif source.startswith('<'):
        if 'ocr_page' in source or 'ocr_line' in source or 'ocrx_word' in source:
            parser=_HOCR();parser.feed(source);source=' '.join(parser.parts);format='hocr'
        else:
            if '<!DOCTYPE' in source.upper() or '<!ENTITY' in source.upper():raise ArchiveError('Declarações externas/entidades não são aceitas no OCR')
            root=ElementTree.fromstring(source)
            if not ('alto' in root.tag.lower() or any('CONTENT' in el.attrib for el in root.iter())):
                raise ArchiveError('XML/HTML não contém OCR ALTO reconhecido')
            lines=[]
            for line in root.iter():
                if line.tag.rsplit('}',1)[-1]=='TextLine':
                    lines.append(' '.join(el.attrib['CONTENT'] for el in line.iter() if 'CONTENT' in el.attrib))
            source='\n'.join(lines) or ' '.join(el.attrib['CONTENT'] for el in root.iter() if 'CONTENT' in el.attrib)
            format='alto_xml'
    source=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',source).strip()
    if not source:raise ArchiveError('Resposta não contém palavras OCR')
    return {'text':source[:max_chars],'format':format,'truncated':len(source)>max_chars,'reading_order':'as_provided'}


class LOCTextService:
    def __init__(self,transport):self.transport=transport;self.settings=service_settings(transport)

    @staticmethod
    def discover(value):
        result=[]
        for url in resource_urls(value):
            parsed=urlparse(url)
            if parsed.path.startswith('/text-services/') or parsed.path.lower().endswith(('.txt','.alto.xml','.ocr.xml','.hocr','.xml')):
                # Metadata APIs sometimes expose ALTO directly instead of a Text Services operation.
                if url not in result:result.append(url)
        return result

    def extract(self,value):
        links=self.discover(value)
        if not self.settings.loc_extract_ocr:
            self.transport.record('loc_text','ocr_extraction','skipped',reason='Extração OCR desabilitada na configuração')
            return {'status':'disabled','pages':[],'text':''}
        if not links:
            self.transport.record('loc_text','ocr_extraction','not_available',reason='Registro não disponibiliza link de texto/OCR reconhecido')
            return {'status':'not_available','pages':[],'text':''}
        pages=[];errors=[]
        for url in links[:self.settings.loc_ocr_max_pages]:
            try:
                raw=self.transport.cached_bytes('loc_text',safe_url(url),max_bytes=2*1024*1024)
                page=parse_ocr(raw,self.settings.loc_ocr_max_chars)
                pages.append({'source_url':url,**page})
                self.transport.record('loc_text','ocr_extraction','passed',format=page['format'],characters=len(page['text']),truncated=page['truncated'],reason='Texto OCR extraído')
            except Exception as exc:
                reason=str(exc) if isinstance(exc,ArchiveError) else 'OCR indisponível ou formato não reconhecido'
                errors.append(reason)
                self.transport.record('loc_text','ocr_extraction','failed',reason=reason)
        return {'status':'available' if pages else 'not_available','pages':pages,
                'text':'\n\n'.join(p['text'] for p in pages),'errors':errors}
