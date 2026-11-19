"""Commons-only conservative metadata policy. Classification is not legal clearance."""
import re
from urllib.parse import urlsplit, urlunsplit
from .providers.common import text
from .manifest import now

VERSION=1
MAPPING={'AUTO_APPROVED':'rights_cleared','NEEDS_REVIEW':'needs_review','REJECTED':'restricted'}


def classify(candidate):
    raw=candidate.metadata.get('record',{})
    raw=raw if isinstance(raw,dict) else {}
    infos=raw.get('imageinfo')
    info=infos[0] if isinstance(infos,list) and infos and isinstance(infos[0],dict) else {}
    ext=info.get('extmetadata')
    ext=ext if isinstance(ext,dict) else {}
    get=lambda name:' '.join(text(ext[name].get('value','') if isinstance(ext.get(name),dict) else '').split())
    name=get('LicenseShortName')
    terms=get('UsageTerms')
    uri=get('LicenseUrl') or candidate.license_url
    copyright_value=get('Copyrighted').casefold()
    required=get('AttributionRequired').casefold()
    notices={k:text(v.get('value','')) for k,v in ext.items() if isinstance(v,dict)
        and any(w in k.casefold() for w in ('restriction','permission','personality','trademark','nonfree'))
        and text(v.get('value','')).casefold() not in {'','false','no','none','0'}}
    categories=[text(c.get('title','')) for c in (raw.get('categories') or []) if isinstance(c,dict)]
    special=[c for c in categories if re.search(r'personality rights|trademark|permission required|non.free',c,re.I)]
    data={'policy_version':VERSION,'checked_at':now(),'license_name':name,'license_url':uri,
        'creator':candidate.creator,'copyright_holder':get('CopyrightHolder') or get('CopyrightOwner'),'credit':get('Credit'),'special_attribution':get('Attribution'),
        'source_url':candidate.source_url,'copyrighted':copyright_value,'attribution_required':None,
        'metadata_attribution_required':required,'notices':notices,'category_notices':special,
        'modifications':[],'classification':'NEEDS_REVIEW','reason':'Metadados incompletos ou licença não reconhecida',
        'license_priority':9,'original_metadata':ext}
    def result(status,reason,*,attribution=None,priority=9):
        data.update(classification=status,reason=reason,attribution_required=attribution,license_priority=priority)
        return data
    combined=' '.join([name,terms,candidate.rights_statement,uri]).casefold()
    if re.search(r'by-nc|by-nd|non.?commercial|no derivatives|all rights reserved|permission required|not (?:in the )?public domain',combined):
        return result('REJECTED','Licença ou restrição incompatível com reutilização comercial automática')
    try:source=urlsplit(candidate.source_url)
    except ValueError:return result('NEEDS_REVIEW','Página original inválida')
    if source.scheme!='https' or source.hostname!='commons.wikimedia.org' or not source.path.startswith('/wiki/File:'):
        return result('NEEDS_REVIEW','Página original do arquivo Commons não confirmada')
    if notices or special or candidate.metadata.get('ai_generated'):
        return result('NEEDS_REVIEW','Avisos especiais de direitos/procedência exigem revisão')
    if not name:return result('NEEDS_REVIEW','Nome da licença ausente nos metadados originais')
    if 'by-sa' in combined or 'share-alike' in combined or 'share alike' in combined:
        return result('NEEDS_REVIEW','CC BY-SA exige revisão das obrigações, especialmente em adaptações',attribution=True)
    try:
        url=urlsplit(uri)
        port=url.port
    except ValueError:return result('NEEDS_REVIEW','URL de licença inválida')
    path=url.path.rstrip('/')
    official=url.scheme=='https' and url.hostname in {'creativecommons.org','www.creativecommons.org'} and not url.username and not url.password and port in (None,443)
    cc0=official and path=='/publicdomain/zero/1.0'
    pdmark=official and path=='/publicdomain/mark/1.0'
    by=official and bool(re.fullmatch(r'/licenses/by/(?:1\.0|2\.0|2\.5|3\.0|4\.0)',path))
    pd=name.strip().rstrip('.').casefold()=='public domain'
    if cc0:
        if 'cc0' not in name.casefold() or required in {'true','1','yes'} or copyright_value=='true':
            return result('NEEDS_REVIEW','Nome/obrigações contradizem a declaração CC0')
        data['license_url']=urlunsplit(('https',url.hostname,path+'/', '', ''))
        return result('AUTO_APPROVED','CC0 explícita, sem avisos adicionais nos metadados',attribution=False,priority=0)
    if pd:
        if (uri and not pdmark) or copyright_value!='false' or required in {'true','1','yes'} or get('License').casefold() not in {'pd','public domain'}:
            return result('NEEDS_REVIEW','Declaração de domínio público incompleta ou contraditória; não inferir liberação pela disponibilidade')
        if terms and terms.strip().rstrip('.').casefold()!='public domain':
            return result('NEEDS_REVIEW','Termos adicionais à declaração de domínio público exigem revisão')
        return result('AUTO_APPROVED','Declaração explícita de domínio público com metadados de copyright consistentes',attribution=False,priority=1)
    if by:
        if not re.fullmatch(r'cc by(?: (?:1\.0|2\.0|2\.5|3\.0|4\.0))?',name.casefold()) or required in {'false','0','no'} or copyright_value=='false':
            return result('NEEDS_REVIEW','Nome/copyright/atribuição contradizem CC BY',attribution=True)
        version=re.search(r'(\d\.\d)',name)
        if version and not path.endswith('/'+version.group(1)):
            return result('NEEDS_REVIEW','Versão da licença contradiz a URL',attribution=True)
        if not candidate.creator.strip() or re.search(r'unknown|not provided|desconhecid',candidate.creator,re.I) or not candidate.attribution:
            return result('NEEDS_REVIEW','CC BY exige autor e crédito completos',attribution=True)
        data['license_url']=urlunsplit(('https',url.hostname,path+'/', '', ''))
        return result('AUTO_APPROVED','CC BY explícita com autor, fonte e atribuição completos',attribution=True,priority=2)
    return data


def update_audit(data,scene_key,item):
    candidate=item['candidate']
    if candidate['provider']!='wikimedia':return
    key=scene_key+':'+item['id']
    record={**item['commons_license'],'scene_key':scene_key,'candidate_id':item['id'],
        'score':item.get('score'),'score_explanation':item.get('score_explanation'),'record_id':candidate['record_id'],'download_url':candidate['download_url'],'title':candidate['title'],'used':item.get('used',False),
        'downloaded_file':item.get('downloaded_file'),'sha256':item.get('sha256'),
        'render_use':item.get('commons_render_use')}
    if record['render_use']:record['modifications']=record['render_use']['modifications']
    data.setdefault('commons_license_audit',{})[key]=record
