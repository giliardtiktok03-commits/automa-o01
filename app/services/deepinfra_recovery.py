"""Explicit, single-use retry authorization for failed DeepInfra scene requests."""
import json
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
from filelock import FileLock
from app.services import deepinfra_image as api, mixed_resume, mixed_materials
from app.utils import utils
from app.utils.atomic_files import write_bytes_atomic


def directory(task_id):
    identity=str(UUID(task_id.strip()))
    root=Path(utils.task_dir()).resolve()
    path=Path(utils.task_dir(identity))
    if not path.resolve().is_relative_to(root):raise ValueError('Pasta do projeto inválida')
    return identity,path


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2*1024*1024:
        raise ValueError('Registro de recuperação DeepInfra inválido')
    result=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result,dict):raise ValueError('Registro de recuperação DeepInfra inválido')
    return result


def failures(task_id):
    _,path=directory(task_id)
    manifest=path/'mixed-scenes.json'
    if not manifest.is_file():return []
    result=[]
    for scene in _read(manifest).get('scenes',[]):
        number=scene.get('id')
        if type(number) is not int or not 1<=number<=mixed_materials.MAX_SHOTS:continue
        if scene.get('image_file') or scene.get('sha256') or scene.get('deepinfra_job')!=f'deepinfra-{number:03d}':continue
        folder=path/'mixed'/f'deepinfra-{number:03d}'
        if not folder.resolve().is_relative_to(path.resolve()):raise ValueError('Pasta DeepInfra fora do projeto')
        state=_read(folder/'deepinfra-image.json')
        if (state.get('status')=='http_error' and state.get('http_status') in api.RETRYABLE_HTTP
                and not (folder/'response.json').exists() and not (folder/'image.png').exists()):
            result.append({'scene_id':number,'http_status':state['http_status'],'request_id':state['request_id']})
    return result


def authorize(task_id,scene_id,request_id,limit,*,deepinfra_unlimited=False,grok_unlimited=False,visual_only=False):
    identity,path=directory(task_id)
    # Never modify the audio, manifest, previous media, or a running render.
    with FileLock(str(path/'mixed-resume.lock'),timeout=0),FileLock(str(path/'mixed-scenes.lock'),timeout=0):
        project=mixed_resume.load(identity,limit,deepinfra_unlimited=deepinfra_unlimited,grok_unlimited=grok_unlimited)
        if not mixed_materials.images_unlimited(project['params']) and project['started']>=limit:
            raise ValueError('Aumente o limite total para incluir uma nova solicitação, ou ative DeepInfra sem limite.')
        expected=next((row for row in failures(identity) if row['scene_id']==scene_id and row['request_id']==request_id),None)
        if not expected:raise ValueError('Esta falha mudou ou já foi autorizada; verifique o projeto novamente.')
        ledger=path/'mixed'/f'deepinfra-{scene_id:03d}'/'deepinfra-image.json'
        with FileLock(str(ledger)+'.lock',timeout=0):
            state=_read(ledger)
            if state.get('status')!='http_error' or state.get('request_id')!=request_id:
                raise ValueError('A solicitação DeepInfra mudou; nenhuma autorização aplicada.')
            if len(state.get('attempt_history',[]))>=50:raise ValueError('Limite de tentativas por cena atingido; revise o projeto.')
            if visual_only:
                scene=next(s for s in project['manifest']['scenes'] if s['id']==scene_id)
                params=project['params'].model_copy(update=scene.get('image_settings') or {})
                params.deepinfra_model=state.get('model') or api.MODEL
                old_prompt,_=mixed_materials.deepinfra_scene_prompt(scene,ledger.parent)
                if api.request_fingerprint(params,old_prompt)!=state.get('fingerprint'):
                    raise ValueError('O pedido salvo diverge do projeto; nenhuma alteração aplicada.')
                state.update(retry_previous_fingerprint=state['fingerprint'],retry_prompt_mode='visual-v1',
                    fingerprint=api.request_fingerprint(params,mixed_materials.image_prompt(scene,visual_only=True)))
            state.update(status='retry_authorized',retry_for=request_id,
                         retry_authorized_at=datetime.now(timezone.utc).isoformat())
            write_bytes_atomic(ledger,json.dumps(state,ensure_ascii=False,indent=2).encode())
    return scene_id
