"""Adapters to the existing scene renderer. Does not replace providers when OFF."""
from pathlib import Path
from app.models.schema import VideoFitMode
from app.services import material
from app.utils import utils
from .service import HistoricalArchiveService
from .contracts import ArchiveError,ArchivePending


def visual_source(path,scene,params,service):
    if Path(path).suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
        duration=(scene['end_frame']-scene['start_frame'])/30
        source=material._render_openai_image_video(path,duration,image_motion=params.image_motion)
        if not source:raise ArchiveError('Não foi possível preparar a imagem histórica; arquivo preservado')
        return source
    return path


def render_params(params,service):
    return params.model_copy(update={'video_fit_mode':VideoFitMode.contain}) if service.settings().preserve_aspect else params


def prepare_legacy(task_id,params,script,duration,subtitle,terms,fallback):
    """Scene-directed archive insertion for local, stock and existing generated sources."""
    from app.services import mixed_materials as mixed
    service=HistoricalArchiveService(task_id)
    if not service.active():return fallback()
    units,_=mixed.timeline(script,duration,subtitle,params.mixed_scene_duration)
    mode=service.settings().mode
    if mode=='historical_research_only':
        for scene in units:
            if not service.active():break
            service.search_scene(scene,terms)
        return fallback()
    directory=Path(utils.task_dir(task_id))
    outputs=[];existing=None
    for index,scene in enumerate(units):
        if service.active():source,provenance=service.select(scene,terms)
        else:source,provenance=None,None
        if source:
            source=visual_source(source,scene,params,service)
            render_settings=render_params(params,service)
        else:
            if existing is None:existing=fallback()
            if not existing:return None
            source=existing[index%len(existing)]
            provenance=None
            render_settings=params
        output=directory/f'archive-scene-{scene["id"]:03d}.mp4'
        mixed.render(source,output,scene['end_frame']-scene['start_frame'],render_settings)
        service.mark_used(provenance)
        outputs.append(str(output))
    params.historical_archive_prepared=True
    return outputs


def save_resume_context(task_id,params,script,terms,audio,subtitle,duration):
    import json
    from .downloader import checksum,local
    from .service import paths
    from app.utils.atomic_files import write_bytes_atomic
    folder,_=paths(task_id)
    root=folder.parent
    records={}
    for name,value in [('audio',audio),('subtitle',subtitle)]:
        if not value:
            records[name]=None
            continue
        path=Path(value).resolve()
        if not path.is_relative_to(root):raise ArchiveError('Mídia de retomada fora do projeto')
        records[name]={'file':str(path.relative_to(root)),'sha256':checksum(path)}
    target=Path(utils.task_dir(task_id))/'historical-archive-resume.json'
    write_bytes_atomic(target,json.dumps({'params':params.model_dump(mode='json'),'script':script,'terms':terms,
        'duration':duration,'media':records},ensure_ascii=False).encode())


def load_resume(task_id):
    import json
    from .service import paths
    from .downloader import local,checksum
    from app.models.schema import VideoParams
    folder,chapter=paths(task_id)
    directory=folder.parent/('chapters/'+chapter if chapter else '')
    if (directory/'final-1.mp4').is_file():raise ArchiveError('Projeto concluído; preserve o vídeo existente')
    data=json.loads((directory/'historical-archive-resume.json').read_text(encoding='utf-8'))
    params=VideoParams.model_validate(data['params'])
    if params.video_source not in {'pexels','pixabay','coverr','local'}:
        raise ArchiveError('Para projetos mistos/imagens use Retomar projeto; capítulos usam a retomada de capítulos existente')
    for name,item in data['media'].items():
        if item and checksum(local(folder.parent,item['file']))!=item['sha256']:raise ArchiveError('Áudio/legenda alterado; retomada interrompida')
        data[name]=str(local(folder.parent,item['file'])) if item else ''
    params.historical_archive_resume=True
    data['params']=params
    return data


def resume(task_id):
    from app.services import task
    from app.services import state as sm
    from app.models import const
    data=load_resume(task_id)
    params=data['params']
    materials=task.get_video_materials(task_id,params,data['terms'],data['duration'],mixed_script=data['script'],mixed_subtitle=data['subtitle'])
    if not materials:raise ArchiveError('Nenhum material disponível para retomar')
    videos,combined,warnings=task.generate_final_videos(task_id,params,materials,data['audio'],data['subtitle'],data['duration'])
    sm.state.update_task(task_id,state=const.TASK_STATE_COMPLETE,progress=100,videos=videos,combined_videos=combined,warnings=warnings)
    return {'task_id':task_id,'videos':videos,'combined_videos':combined,'warnings':warnings}
