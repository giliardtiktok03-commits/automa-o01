"""Assisted Google Flow imports. No browser automation, accounts or paid fallback."""
import hashlib
import io
import json
import re
from pathlib import Path
from uuid import UUID

from filelock import FileLock
from PIL import Image

from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic


class FlowError(ValueError):
    pass


class FlowWaiting(FlowError):
    task_id = ''  # There is no remote task ID in manual mode.


def _save(path, value):
    write_bytes_atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def export(directory, manifest, aspect, prompt_builder):
    folder=Path(directory)/'google-flow'
    folder.mkdir(exist_ok=True)
    entries=[]
    for scene in manifest['scenes']:
        if scene.get('sha256') or scene.get('image_file') or (scene.get('image_request_started') and not scene.get('google_flow_job')):
            continue
        prompt=prompt_builder(scene)
        digest=hashlib.sha256(json.dumps({'prompt':prompt,'aspect':aspect},sort_keys=True).encode()).hexdigest()
        entries.append({'scene_id':scene['id'],'text':scene['text'],'prompt':prompt,'aspect_ratio':aspect,
                        'fingerprint':digest,'filename':f"scene-{scene['id']:03d}.png",
                        'status':'needed' if scene.get('flow_waiting') else 'candidate'})
    _save(folder/'requests.json',{'version':1,'provider':'google_flow','access_mode':'manual_import','scenes':entries})
    markdown='# Google Flow — imagens por cena\n\nGere manualmente no Flow. Importe cada imagem pelo número da cena. Candidatas podem ser atendidas pelos bancos; não é preciso gerar todas.\n\n'
    for item in entries:
        markdown+=f"## Cena {item['scene_id']:03d} · {item['status']} · {aspect}\n\n{item['prompt']}\n\n"
    write_bytes_atomic(folder/'flow_prompts.md',markdown.encode('utf-8'))
    return folder


def project(task_id):
    try:
        parts=str(task_id).replace('\\','/').split('/')
        task_id=str(UUID(parts[0]))
        suffix=[]
        if len(parts)!=1:
            if len(parts)!=3 or parts[1]!='chapters' or not re.fullmatch(r'[0-9]{3}',parts[2]) or int(parts[2])<1:
                raise ValueError()
            suffix=['chapters',parts[2]]
    except (ValueError,TypeError,AttributeError):
        raise FlowError('Informe o ID UUID do projeto, opcionalmente com /chapters/001') from None
    root=Path(utils.task_dir()).resolve()
    folder=root/task_id/Path(*suffix)/'google-flow'
    if not folder.is_dir() or not folder.resolve().is_relative_to(root) or folder.is_symlink():
        raise FlowError('Este projeto ainda não exportou prompts Flow. Inicie a geração com Flow selecionado.')
    return folder


def read_requests(folder):
    return json.loads((Path(folder)/'requests.json').read_text(encoding='utf-8'))


def import_image(task_id, scene_id, content):
    folder=project(task_id)
    with FileLock(str(folder/'import.lock'),timeout=0):
        request=next((s for s in read_requests(folder)['scenes'] if s['scene_id']==scene_id),None)
        if not request:
            raise FlowError('Cena não está na lista de solicitações Flow deste projeto')
        if not isinstance(content,bytes) or not content or len(content)>25*1024*1024:
            raise FlowError('Importe uma imagem de até 25 MB')
        try:
            with Image.open(io.BytesIO(content)) as source:
                if source.width<64 or source.height<64 or source.width*source.height>30_000_000:
                    raise ValueError()
                source.load()
                output=io.BytesIO()
                source.convert('RGB').save(output,format='PNG')
                dimensions=source.size
        except Exception:
            raise FlowError('Arquivo inválido: envie PNG, JPG ou WebP válido com dimensões adequadas') from None
        target=folder/f'scene-{scene_id:03d}.png'
        meta=folder/f'scene-{scene_id:03d}.json'
        data=output.getvalue()
        digest=hashlib.sha256(data).hexdigest()
        if target.exists():
            if meta.exists() and json.loads(meta.read_text()).get('sha256')==digest and hashlib.sha256(target.read_bytes()).hexdigest()==digest:
                return target
            raise FlowError('Esta cena já possui imagem importada; o arquivo existente foi preservado')
        write_bytes_atomic(target,data)
        _save(meta,{'version':1,'provider':'google_flow','access_mode':'manual_import','scene_id':scene_id,
                    'fingerprint':request['fingerprint'],'sha256':digest,'width':dimensions[0],'height':dimensions[1],
                    'illustration':True,'source_type':'ai_generated_reconstruction'})
        return target


def receive(folder, scene_id):
    folder=Path(folder)
    request=next((s for s in read_requests(folder)['scenes'] if s['scene_id']==scene_id),None)
    target=folder/f'scene-{scene_id:03d}.png'
    meta=folder/f'scene-{scene_id:03d}.json'
    if not target.exists() and not meta.exists():
        raise FlowWaiting(f'Aguardando imagem Flow da cena {scene_id:03d}. Exporte os prompts e importe a imagem em Configurar fontes de material → Google Flow. Depois retome o mesmo projeto.')
    if not request or not target.is_file() or not meta.is_file():
        raise FlowError('Importação Flow incompleta; revise os arquivos sem gerar novamente')
    metadata=json.loads(meta.read_text(encoding='utf-8'))
    if metadata.get('fingerprint')!=request['fingerprint'] or metadata.get('sha256')!=hashlib.sha256(target.read_bytes()).hexdigest():
        raise FlowError('A imagem Flow ou o pedido foi alterado; revise a associação da cena')
    return target,metadata


def freeze(params,settings):
    from app.services import flow_browser
    defaults={'google_flow_mode':('google_flow_access_mode','automatic'),
              'google_flow_profile':('google_flow_profile','principal'),
              'google_flow_project_url':('google_flow_project_url',''),
              'google_flow_model':('google_flow_model','Nano Banana 2.1'),
              'google_flow_timeout':('google_flow_timeout_seconds',900),
              'google_flow_require_zero':('google_flow_require_zero',True)}
    for name,(key,default) in defaults.items():
        if getattr(params,name) is None:setattr(params,name,settings.get(key,default))
    if params.google_flow_mode not in ('automatic','manual_import') or params.google_flow_model not in ('Nano Banana 2.1','Nano Banana 2','Nano Banana 2 Lite'):
        raise FlowError('Modo ou modelo Flow inválido')
    if params.google_flow_mode=='automatic':
        try:
            flow_browser.validate(params.google_flow_profile,params.google_flow_project_url)
            flow_browser._chrome_executable()
        except flow_browser.FlowError as exc:raise FlowError(str(exc)) from exc


def generate(params,prompt,folder,scene_id,job_folder,*,before_submit=None):
    from app.services import flow_browser
    try:
        return receive(folder,scene_id)
    except FlowWaiting:
        if params.google_flow_mode!='automatic':raise
    image=flow_browser.generate(prompt,job_folder,params.google_flow_profile,params.google_flow_project_url,
        timeout=params.google_flow_timeout,require_zero=params.google_flow_require_zero,
        aspect=getattr(params.video_aspect,'value',params.video_aspect),model=params.google_flow_model,
        before_submit=before_submit)
    # Validate and normalize through the same import contract used for recovery.
    request=next((s for s in read_requests(folder)['scenes'] if s['scene_id']==scene_id),None)
    if not request:raise FlowError('Pedido Flow da cena não foi encontrado')
    with Image.open(image) as source:
        source.load()
        out=io.BytesIO()
        source.convert('RGB').save(out,format='PNG')
        size=source.size
    target=Path(folder)/f'scene-{scene_id:03d}.png'
    data=out.getvalue()
    write_bytes_atomic(target,data)
    _save(Path(folder)/f'scene-{scene_id:03d}.json',{'version':1,'provider':'google_flow','access_mode':'automatic',
         'model':params.google_flow_model,'scene_id':scene_id,'fingerprint':request['fingerprint'],
         'sha256':hashlib.sha256(data).hexdigest(),'width':size[0],'height':size[1],
         'illustration':True,'source_type':'ai_generated_reconstruction'})
    return receive(folder,scene_id)
