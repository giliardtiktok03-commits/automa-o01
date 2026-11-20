"""Bind used Commons images to real render files and the final video, then credit."""
import hashlib
import json
from pathlib import Path, PureWindowsPath, PurePosixPath
import os
import traceback
from filelock import FileLock
from app.utils.atomic_files import write_bytes_atomic
from .contracts import ArchiveError
from .downloader import local
from .manifest import now
from .commons_license import classify

HEADER='Historical Image Credits'


def digest(file):
    sha=hashlib.sha256()
    with Path(file).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block)
    return sha.hexdigest()


def put(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    write_bytes_atomic(path,json.dumps(data,ensure_ascii=False,indent=2).encode())


def load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default
    except (ValueError,OSError):raise ArchiveError('Auditoria Commons inválida; revisão necessária') from None


def has_commons(folder):
    data=load(Path(folder)/'manifest.json',{})
    return bool(load(Path(folder)/'commons-final-media.json',{}).get('videos')) or any(i.get('used') and i.get('candidate',{}).get('provider')=='wikimedia'
        for scene in data.get('scenes',{}).values() for i in scene.get('candidates',[]))


def relative_name(value):
    if not isinstance(value,str) or not value or ':' in value:raise ArchiveError('Caminho de auditoria inválido')
    path=PureWindowsPath(value) if '\\' in value else PurePosixPath(value)
    if path.is_absolute() or getattr(path,'drive','') or '..' in path.parts:
        raise ArchiveError('Caminho de auditoria fora do projeto')
    return '/'.join(path.parts)


def path_key(value):
    return os.path.normcase(relative_name(value))


def project_file(root,value):
    return local(root,relative_name(value))


def entry_for(records,name):
    matches=[v for k,v in records.items() if path_key(k)==path_key(name)]
    if len(matches)>1:raise ArchiveError('Auditoria contém caminhos duplicados para o mesmo vídeo')
    return matches[0] if matches else None


def error_report(folder,video,exc):
    reason=str(exc) if isinstance(exc,ArchiveError) else 'Falha na conferência de créditos ('+type(exc).__name__+'); consulte o diagnóstico técnico'
    original=exc
    visited=set()
    while original.__cause__ is not None and id(original) not in visited:
        visited.add(id(original));original=original.__cause__
    frames=[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(original.__traceback__)[-8:]]
    put(Path(folder)/'commons-publication-review.json',{'status':'NEEDS_REVIEW','checked_at':now(),
        'reason':reason,'error_type':type(original).__name__,'error_stage':'commons_credits',
        'technical_frames':frames,'published':False,'automatic_publication':False})
    return reason


def record_use(folder,item,output,params):
    if not output or params is None:
        return None  # Legacy records remain preserved, but won't pass publication reconciliation.
    folder=Path(folder);root=folder.parent.resolve();output=Path(output).resolve()
    if not output.is_relative_to(root) or not output.is_file():raise ArchiveError('Cena Commons fora do projeto ou ausente')
    return {'render_file':output.relative_to(root).as_posix(),'render_sha256':digest(output),
        'recorded_at':now(),'modifications':['Converted to RGB PNG',
        'Image motion: '+str(getattr(params.image_motion,'value',params.image_motion)),
        'Fit mode: '+str(getattr(params.video_fit_mode,'value',params.video_fit_mode)),
        'Output aspect ratio: '+str(getattr(params.video_aspect,'value',params.video_aspect)),
        'Crop to fill frame' if str(getattr(params.video_fit_mode,'value',params.video_fit_mode))=='cover' else 'Padding preserves original aspect ratio',
        'No color correction requested in this pipeline']}


def used(folder):
    data=load(Path(folder)/'manifest.json',{})
    return [(key,item) for key,scene in data.get('scenes',{}).items() for item in scene.get('candidates',[])
        if item.get('used') and item.get('candidate',{}).get('provider')=='wikimedia']


def locate(video):
    for parent in list(Path(video).resolve().parents)[:4]:
        folder=parent/'historical_archive'
        if (folder/'manifest.json').is_file() or (folder/'commons-final-media.json').is_file():return folder
    return None


def _bind_final(task_id,video,parts):
    from .service import paths
    folder,_=paths(task_id)
    rows=used(folder)
    if not rows:return None
    root=folder.parent.resolve();video=Path(video).resolve()
    if not video.is_relative_to(root):raise ArchiveError('Vídeo Commons fora do projeto')
    parts={Path(p).resolve():digest(p) for p in parts}
    bindings=[]
    for key,item in rows:
        proof=item.get('commons_render_use')
        if not proof:continue
        output=project_file(root,proof['render_file'])
        if output not in parts:continue  # Other chapters/outputs do not belong to this video.
        if proof['render_sha256']!=parts[output]:raise ArchiveError('Cena Commons alterada antes da montagem final')
        bindings.append({'scene_key':key,'candidate_id':item['id'],'render_file':relative_name(proof['render_file']),
            'render_sha256':proof['render_sha256']})
    # An untracked legacy use cannot be silently declared licensed.
    if not bindings and any(not item.get('commons_render_use') for _,item in rows):
        raise ArchiveError('Uso Commons sem comprovante de renderização; revisão necessária')
    record={'video_file':video.relative_to(root).as_posix(),'video_sha256':digest(video),'checked_at':now(),
        'bindings':bindings,'parts':[{'file':p.relative_to(root).as_posix(),'sha256':s} for p,s in parts.items()],
        'automatic_publication':False}
    with FileLock(str(folder/'commons-final-media.lock'),timeout=60):
        data=load(folder/'commons-final-media.json',{'version':1,'videos':{}})
        for old_name in list(data['videos']):
            if path_key(old_name)==path_key(record['video_file']):del data['videos'][old_name]
        data['videos'][record['video_file']]=record;put(folder/'commons-final-media.json',data)
    return record


def bind_final(task_id,video,parts):
    try:
        record=_bind_final(task_id,video,parts)
        if record and record['bindings']:prepare_description(video,'')
        return record
    except Exception as exc:
        from .service import paths
        folder,_=paths(task_id)
        reason=error_report(folder,video,exc)
        raise ArchiveError(reason) from exc



def prepare_description(video,description,limit=5000):
    folder=locate(video)
    if folder is None:return description
    root=folder.parent.resolve();video=Path(video).resolve()
    report={'checked_at':now(),'video_file':video.relative_to(root).as_posix(),'published':False,'automatic_publication':False}
    try:
        if not has_commons(folder):return description
        if not isinstance(description,str):raise ArchiveError('Descrição inválida; revisão necessária')
        records=load(folder/'commons-final-media.json',{}).get('videos',{})
        record=entry_for(records,video.relative_to(root).as_posix())
        if not record or record['video_sha256']!=digest(video):raise ArchiveError('Vídeo final sem comprovante ou alterado após a montagem')
        for part in record['parts']:
            if digest(project_file(root,part['file']))!=part['sha256']:raise ArchiveError('Material de montagem alterado; créditos exigem revisão')
        all_items={(k,i['id']):i for k,i in used(folder)}
        part_names={path_key(p['file']) for p in record['parts']}
        expected={(k,i['id']) for k,i in used(folder) if (i.get('commons_render_use') or {}).get('render_file') and path_key(i['commons_render_use']['render_file']) in part_names}
        actual={(b['scene_key'],b['candidate_id']) for b in record['bindings']}
        if expected!=actual:raise ArchiveError('A lista final de imagens diverge dos créditos vinculados')
        if not record['bindings']:
            report.update(status='ready_for_manual_publication',image_count=0)
            put(folder/'commons-publication-review.json',report)
            return description
        chosen=[]
        from .contracts import ArchiveCandidate
        for binding in record['bindings']:
            item=all_items.get((binding['scene_key'],binding['candidate_id']))
            if not item:raise ArchiveError('Créditos divergem da lista de imagens usada no vídeo')
            proof=item.get('commons_render_use') or {}
            if path_key(proof.get('render_file',''))!=path_key(binding['render_file']) or proof.get('render_sha256')!=binding['render_sha256']:
                raise ArchiveError('Comprovante de uso da imagem divergente')
            source=project_file(folder,item['downloaded_file'])
            if digest(source)!=item['sha256']:raise ArchiveError('Imagem Commons alterada ou ausente')
            c=ArchiveCandidate(**item['candidate']);decision=classify(c)
            if decision['classification']!='AUTO_APPROVED':raise ArchiveError('Imagem Commons requer revisão: '+decision['reason'])
            if not proof.get('modifications'):raise ArchiveError('Modificações da imagem não registradas')
            chosen.append((c,decision,proof['modifications']))
        if not chosen:raise ArchiveError('Nenhum crédito Commons reconciliado com o vídeo')
        lines=[HEADER]
        seen=set()
        for c,decision,mods in chosen:
            if c.record_id in seen:continue
            seen.add(c.record_id)
            author=c.creator or 'Creator not specified in the Commons record'
            credit_parts=list(dict.fromkeys(v for v in [decision['credit'],decision['special_attribution']] if v))
            credit='; '.join(credit_parts) or c.attribution
            lines.extend(['',c.title,'Creator: '+author])
            if decision.get('copyright_holder'):lines.append('Copyright holder: '+decision['copyright_holder'])
            lines.extend(['Source: '+c.source_url,
                'License: '+decision['license_name']+((' — '+decision['license_url']) if decision['license_url'] else ' (as declared in the Commons record)'),
                'Credit: '+credit,
                'Changes: '+'; '.join(mods)])
        block='\n'.join(lines)
        # Idempotent for an unchanged generated block; never delete arbitrary user text.
        previous=entry_for(load(folder/'commons-description-block.json',{}),video.relative_to(root).as_posix())
        base=description
        if previous and base.endswith('\n\n'+previous):base=base[:-(len(previous)+2)]
        if HEADER in base:raise ArchiveError('Bloco de créditos pré-existente precisa ser reconciliado; nenhum texto SEO foi removido')
        combined=base.rstrip()+'\n\n'+block
        if len(combined.encode('utf-8'))>limit:raise ArchiveError('Descrição e créditos excedem o limite do YouTube; revise sem remover atribuições obrigatórias')
        with FileLock(str(folder/'commons-description.lock'),timeout=60):
            blocks=load(folder/'commons-description-block.json',{})
            for old_name in list(blocks):
                if path_key(old_name)==path_key(video.relative_to(root).as_posix()):del blocks[old_name]
            blocks[video.relative_to(root).as_posix()]=block
            put(folder/'commons-description-block.json',blocks)
        write_bytes_atomic(folder/'historical-image-credits.txt',block.encode('utf-8'))
        write_bytes_atomic(folder/'youtube-description-with-credits.txt',combined.encode('utf-8'))
        report.update(status='ready_for_manual_publication',image_count=len(seen),description_characters=len(combined),description_utf8_bytes=len(combined.encode('utf-8')),
            license_checks=[{'record_id':c.record_id,'classification':d['classification'],'checked_at':d['checked_at']} for c,d,_ in chosen])
        put(folder/'commons-publication-review.json',report)
        return combined
    except Exception as exc:
        reason=error_report(folder,video,exc)
        raise ArchiveError(reason) from exc
