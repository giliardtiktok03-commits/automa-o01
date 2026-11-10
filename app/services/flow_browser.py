"""Visible Chrome Flow driver. Manual login, localhost CDP, no private API."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse
import uuid
import hashlib

from filelock import FileLock, Timeout
from PIL import Image

from app.utils import utils
from app.services import task_artifacts
from app.utils.atomic_files import write_bytes_atomic


from app.services.flow_errors import FlowError, FlowRefusal


def normalized(profile,project):
    def trim(value):return str(value or '').strip().strip('\u200b\ufeff').strip()
    return trim(profile),trim(project)


def validate(profile,project):
    profile,project=normalized(profile,project)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',profile):
        raise FlowError('Use um nome de perfil com 1–48 letras, números, hífen ou sublinhado',key='flow.invalid_profile')
    u=urlparse(project)
    if u.scheme!='https' or u.netloc!='flow.google.com' or u.query or u.fragment or not re.fullmatch(r'/project/[0-9a-fA-F-]{36}/?',u.path):
        raise FlowError('Use o link HTTPS do projeto Flow, sem parâmetros adicionais',key='flow.invalid_project')
    try:uuid.UUID(u.path.strip('/').split('/')[-1])
    except ValueError:raise FlowError('ID do projeto Flow inválido') from None
    if importlib.util.find_spec('playwright') is None:
        raise FlowError('Execute PREPARAR_FLOW_WINDOWS.bat para instalar Playwright',key='flow.setup_required')


def _root():return Path(utils.storage_dir('flow_browser',create=True))


def _launch(request):
    return subprocess.Popen([sys.executable,'-m','app.services.flow_browser','--request',str(request)],cwd=utils.root_dir(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def _chrome_executable():
    if os.name=='nt':
        for variable in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
            base=os.environ.get(variable)
            if base:
                candidate=Path(base)/'Google'/'Chrome'/'Application'/'chrome.exe'
                if candidate.is_file():return str(candidate)
    else:
        for name in ('google-chrome','google-chrome-stable','chromium','chromium-browser'):
            found=shutil.which(name)
            if found:return found
    raise FlowError('Instale o Google Chrome para usar o Flow no navegador')


def connect(profile,project):
    profile,project=normalized(profile,project)
    validate(profile,project)
    folder=_root()/'requests'
    folder.mkdir(exist_ok=True)
    request=folder/(uuid.uuid4().hex+'.json')
    task_artifacts._write_json_atomic(request,{'profile':profile,'project':project,'action':'connect'})
    _launch(request)
    return request.with_suffix('.result.json')


def start_test(profile,project,require_zero=True,*,model="Nano Banana 2.1",aspect="16:9"):
    profile,project=normalized(profile,project)
    validate(profile,project)
    folder=_root()/'tests'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    request=folder/'flow-request.json'
    task_artifacts._write_json_atomic(request,{'profile':profile,'project':project,'action':'generate','timeout':180,
         'require_zero':require_zero,'aspect':aspect,'model':model,
         'prompt':'A cozy empty cafe on a rainy morning, warm lighting, photorealistic, no text, no logos.'})
    _launch(request)
    return request


def latest_test(profile):
    folder=_root()/'tests'
    matches=[]
    for path in folder.glob('*/flow-request.json'):
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('action')=='generate' and data.get('profile')==profile:
                matches.append((path.stat().st_mtime_ns,path,data))
        except (OSError,ValueError):
            continue
    return max(matches,key=lambda entry:entry[0]) if matches else None


def start_inspection(profile,project,*,use_latest_test=False):
    profile,project=normalized(profile,project)
    if use_latest_test:
        previous=latest_test(profile)
        if previous:project=previous[2]['project']
    validate(profile,project)
    folder=_root()/'tests'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    request=folder/'flow-request.json'
    task_artifacts._write_json_atomic(request,{'profile':profile,'project':project,'action':'inspect'})
    _launch(request)
    return request


def start_recovery(profile,project,title):
    profile,project=normalized(profile,project)
    previous=latest_test(profile)
    if previous:project=previous[2]['project']
    validate(profile,project)
    title=str(title or '').strip()
    if not title or len(title)>200:raise FlowError('Informe o título exato da imagem existente')
    folder=_root()/'tests'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    request=folder/'flow-request.json'
    task_artifacts._write_json_atomic(request,{'profile':profile,'project':project,'action':'recover','asset_title':title})
    _launch(request)
    return request


def generate(prompt,directory,profile,project,timeout=900,require_zero=True,*,aspect='16:9',model='Nano Banana 2.1',before_submit=None):
    profile,project=normalized(profile,project)
    validate(profile,project)
    if aspect not in ('16:9','9:16','1:1') or not 30<=int(timeout)<=1800 or model not in ('Nano Banana 2.1','Nano Banana 2','Nano Banana 2 Lite'):
        raise FlowError('Configurações Flow inválidas: confira proporção, modelo e tempo de espera')
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>10000:
        raise FlowError('Prompt Flow inválido')
    folder=Path(directory)
    folder.mkdir(parents=True,exist_ok=True)
    request=folder/'flow-request.json'
    result_file=request.with_suffix('.result.json')
    submitted_file=request.with_suffix('.submitted.json')
    ledger=folder/'flow-image.json'
    spec={'prompt':prompt,'profile':profile,'project':project,'aspect':aspect,'model':model,'require_zero':require_zero}
    fingerprint=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    with FileLock(str(ledger)+'.lock',timeout=0):
        state=json.loads(ledger.read_text()) if ledger.exists() else None
        if state and state.get('fingerprint')!=fingerprint:
            raise FlowError('Configurações diferentes da tentativa Flow salva; revise antes de gerar outra imagem')
        if result_file.is_file():
            result=json.loads(result_file.read_text())
            if result.get('status')=='ready':
                image=request.with_suffix('.png')
                if not image.is_file():raise FlowError('Imagem Flow recebida está ausente; revise sem reenviar')
                data=image.read_bytes()
                if state and state.get('sha256') and state['sha256']!=hashlib.sha256(data).hexdigest():
                    raise FlowError('Imagem Flow salva foi alterada; nenhum novo envio')
                if state:
                    state.update(status='saved',sha256=hashlib.sha256(data).hexdigest())
                    task_artifacts._write_json_atomic(ledger,state)
                return image
            if result.get('status')=='refused':raise FlowRefusal('Flow recusou explicitamente o pedido; sem reformulação')
            if submitted_file.exists() or result.get('submitted'):
                raise FlowError('Resultado Flow não confirmado após envio. Confira o projeto no Chrome e importe a imagem, sem gerar novamente.')
            # Failed before submission: explicit resume may try the controls again.
            result_file.unlink()
            request.with_suffix('.diagnostic.json').unlink(missing_ok=True)
        elif request.exists():
            raise FlowError('Tentativa Flow existente sem resultado confirmado. Confira o Chrome; nenhum novo envio automático.')
        if not state:
            state={'version':1,'provider':'google_flow','request_id':str(uuid.uuid4()),'fingerprint':fingerprint,'status':'prepared'}
            task_artifacts._write_json_atomic(ledger,state)
            if before_submit:before_submit()
        task_artifacts._write_json_atomic(request,{**spec,'action':'generate','timeout':int(timeout)})
        process=_launch(request)
        try:process.wait(timeout=int(timeout)+120)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:pass
            raise FlowError('Tempo de espera Flow atingido; revise a tentativa existente antes de continuar') from None
        if not result_file.is_file():raise FlowError('Navegador encerrou sem confirmar resultado; pedido preservado, sem reenvio')
        result=json.loads(result_file.read_text())
        if result.get('status')=='refused':raise FlowRefusal('Flow recusou explicitamente o pedido; sem reformulação')
        if result.get('status')!='ready':raise FlowError(result.get('error') or 'Flow não entregou uma imagem; sem reenvio automático')
        image=request.with_suffix('.png')
        if not image.is_file():raise FlowError('Flow não salvou a imagem; tentativa preservada')
        state.update(status='saved',sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        task_artifacts._write_json_atomic(ledger,state)
        return image


def _save_image(download,target):
    target=Path(target)
    temporary=target.with_suffix('.download')
    try:
        download.save_as(str(temporary))
        if temporary.stat().st_size>25*1024*1024:raise FlowError('Imagem baixada excede 25 MB')
        with Image.open(temporary) as image:
            if image.width*image.height>30_000_000:raise FlowError('Imagem excede o limite de pixels')
            image.load()
            buffer=io.BytesIO()
            image.convert('RGB').save(buffer,format='PNG')
            write_bytes_atomic(target,buffer.getvalue())
    finally:temporary.unlink(missing_ok=True)


def _wait_devtools(chrome, port_file, timeout=45):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            lines=port_file.read_text().splitlines()
            if lines and lines[0].isdigit() and 1024<=int(lines[0])<=65535:
                return lines[0]
        except (OSError,UnicodeError):
            pass
        if chrome.poll() not in (None,0):
            raise FlowError('Chrome encerrou antes de disponibilizar a conexão local')
        time.sleep(.25)
    raise FlowError('Chrome não disponibilizou a conexão local. Feche todas as janelas deste perfil e tente novamente.')


def _diagnostic(request_file,page,stage,exc,submitted):
    data={'stage':stage,'exception_type':type(exc).__name__,'submitted':submitted}
    if isinstance(exc,FlowError):data['reason']=str(exc)[:500]
    try:
        if page and urlparse(page.url).hostname=='flow.google.com':
            path=urlparse(page.url).path
            if re.fullmatch(r'/project/[0-9a-fA-F-]{36}/?',path):data['project_id']=path.strip('/').split('/')[-1]
            if stage in ('localizando_imagem_existente','localizando_imagem_gerada','aguardando_controles_da_imagem'):
                request_data=json.loads(request_file.read_text(encoding='utf-8'))
                title=str(request_data.get('asset_title',''))[:200]
                if not re.search(r'@|https?://',title):data['requested_asset_title']=title
                data['image_ancestors']=page.evaluate("""() => Array.from(document.querySelectorAll('img')).filter(el=>el.getClientRects().length && el.naturalWidth>=128).slice(0,12).map(img=>{let result=[],el=img.parentElement;for(let i=0;el && el!==document.body && i<24;i++,el=el.parentElement){result.push({tag:el.tagName,images:el.querySelectorAll('img').length,buttons:Array.from(el.querySelectorAll('button')).slice(0,10).map(b=>(b.getAttribute('aria-label')||b.innerText||'').slice(0,120)).filter(t=>!/@|https?:|account|conta do google/i.test(t))});}return result})""")
            body=page.locator('body').inner_text(timeout=3000)
            keywords=re.compile(r'erro|error|failed|não foi possível|something went wrong|try again|tentar de novo|quota|limite|blocked|atividade incomum|unusual',re.I)
            data['visible_messages']=[line.strip()[:300] for line in body.splitlines() if keywords.search(line) and not re.search(r'@|https?://',line)][:12]
            data['images']=page.evaluate("""() => Array.from(document.querySelectorAll('img')).filter(el=>el.getClientRects().length).slice(0,20).map(el=>({width:el.naturalWidth,height:el.naturalHeight,complete:el.complete,alt:(el.alt||'').slice(0,100),button_label:(el.closest('button')?.getAttribute('aria-label')||'').slice(0,100)})).filter(x=>!/@|https?:|account|conta do google/i.test(x.alt+' '+x.button_label))""")
            data['controls']=page.evaluate("""() => Array.from(document.querySelectorAll('button,[role=tab],[role=combobox],textarea,[contenteditable=true]')).filter(el=>el.getClientRects().length).slice(0,80).map(el=>({tag:el.tagName,role:el.getAttribute('role'),label:(el.getAttribute('aria-label')||el.innerText||el.getAttribute('placeholder')||'').slice(0,120),selected:el.getAttribute('aria-checked')||el.getAttribute('aria-selected')||el.getAttribute('aria-pressed')||el.getAttribute('data-state')})).filter(x=>!/@|https?:|account|conta do google/i.test(x.label))""")
    except Exception:
        pass
    task_artifacts._write_json_atomic(request_file.with_suffix('.diagnostic.json'),data)


def _browser(request_file):
    result_file=request_file.with_suffix('.result.json')
    marker=request_file.with_suffix('.submitted.json')
    chrome=None
    page=None
    stage='preparando_perfil'
    try:
        data=json.loads(request_file.read_text(encoding='utf-8'))
        validate(data['profile'],data['project'])
        profiles=_root()/'profiles'
        profiles.mkdir(exist_ok=True)
        profile=(profiles/data['profile']).resolve()
        profile.mkdir(exist_ok=True)
        # One Flow operation on this MPT installation at a time; never kill other Chrome instances.
        with FileLock(str(_root()/'machine.lock'),timeout=0),FileLock(str(profiles/(data['profile']+'.lock')),timeout=0):
            if not profile.resolve().is_relative_to(profiles.resolve()):raise FlowError('Perfil Flow deve ficar na pasta local do MPT')
            command=[_chrome_executable(),'--user-data-dir='+str(profile),'--no-first-run','--disable-background-mode',data['project']]
            if data['action']=='connect':
                # Ordinary installed Chrome: no automation connection during Google login.
                chrome=subprocess.Popen(command)
                chrome.wait()
                task_artifacts._write_json_atomic(result_file,{'status':'closed'})
                return
            port_file=profile/'DevToolsActivePort'
            port_file.unlink(missing_ok=True)
            chrome=subprocess.Popen(command[:-1]+['--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',data['project']])
            stage='aguardando_porta_chrome'
            port_text=_wait_devtools(chrome,port_file)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                stage='conectando_chrome'
                browser=p.chromium.connect_over_cdp('http://127.0.0.1:'+port_text,timeout=30000)
                try:
                    stage='abrindo_projeto'
                    if not browser.contexts:raise FlowError('Chrome conectou sem contexto disponível; feche o perfil e tente novamente')
                    context=browser.contexts[0]
                    page=next((item for item in context.pages if urlparse(item.url).hostname=='flow.google.com'),None)
                    if page is None:page=context.pages[0] if context.pages else context.new_page()
                    if page.url.rstrip('/')!=data['project'].rstrip('/'):
                        page.goto(data['project'],wait_until='domcontentloaded',timeout=60000)
                    def report(value):
                        nonlocal stage
                        stage=value
                    if data['action']=='recover':
                        from app.services import flow_automation
                        flow_automation.recover(page,data['asset_title'],request_file.with_suffix('.png'),on_stage=report)
                        task_artifacts._write_json_atomic(result_file,{'status':'recovered','submitted':False,'stage':stage})
                        return
                    if data['action']=='inspect':
                        stage='verificacao_somente_leitura'
                        if urlparse(page.url).hostname!='flow.google.com':raise FlowError('A sessão requer login manual no Google')
                        page.locator('textarea, [contenteditable="true"]').first.wait_for(state='visible',timeout=30000)
                        page.wait_for_timeout(1000)
                        _diagnostic(request_file,page,stage,FlowError('Verificação somente leitura; nenhum pedido enviado'),False)
                        task_artifacts._write_json_atomic(result_file,{'status':'inspected','submitted':False,'stage':stage})
                        return
                    from app.services import flow_automation
                    def mark():
                        task_artifacts._write_json_atomic(marker,{'submitted':True})
                    flow_automation.generate(page,data['prompt'],request_file.with_suffix('.png'),timeout=data.get('timeout',900),
                        require_zero=data.get('require_zero',True),aspect=data.get('aspect','16:9'),model_name=data.get('model','Nano Banana 2.1'),before_submit=mark,on_stage=report)
                    task_artifacts._write_json_atomic(result_file,{'status':'ready','submitted':True})
                except Exception as exc:
                    _diagnostic(request_file,page,stage,exc,marker.exists())
                    raise
                finally:
                    try:browser.new_browser_cdp_session().send('Browser.close')
                    except Exception:pass
                    try:browser.close()
                    except Exception:pass
    except Timeout:
        task_artifacts._write_json_atomic(result_file,{'status':'failed','submitted':marker.exists(),'error':'Este perfil ou navegador Flow está em uso. Feche a janela de login antes de gerar.'})
    except FlowRefusal:
        task_artifacts._write_json_atomic(result_file,{'status':'refused','submitted':marker.exists()})
    except FlowError as exc:
        if not request_file.with_suffix('.diagnostic.json').exists():
            _diagnostic(request_file,page,stage,exc,marker.exists())
        task_artifacts._write_json_atomic(result_file,{'status':'failed','stage':stage,'submitted':marker.exists(),'error':f'{stage}: {exc}'})
    except Exception as exc:
        if not request_file.with_suffix('.diagnostic.json').exists():
            _diagnostic(request_file,page,stage,exc,marker.exists())
        task_artifacts._write_json_atomic(result_file,{'status':'failed','stage':stage,'submitted':marker.exists(),'error':f'Flow parou em {stage} ({type(exc).__name__}). Diagnóstico local disponível; nenhum reenvio automático.'})
    finally:
        if chrome is not None:
            try:
                if chrome.poll() is None:
                    chrome.terminate()
                    chrome.wait(timeout=5)
            except Exception:pass


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True)
    _browser(Path(parser.parse_args().request).resolve())
