import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from PIL import Image
from app.services import flow_browser as flow

URL = 'https://flow.google.com/project/39a3cd68-17c5-4695-8c99-52ea21b38e66'


@pytest.mark.parametrize('profile,url', [('..',URL), ('a/b',URL), ('principal','https://evil.test/project/a'),
                                      ('principal', URL+'?token=private'), ('principal','http://flow.google.com/project/a')])
def test_profile_and_project_are_restricted(profile, url):
    with pytest.raises(ValueError):
        flow.validate(profile, url)


def test_missing_optional_dependency_is_reported_before_browser_launch(monkeypatch):
    monkeypatch.setattr(flow.importlib.util, 'find_spec', lambda *_: None)
    with pytest.raises(flow.FlowError, match='PREPARAR_FLOW_WINDOWS'):
        flow.validate('principal', URL)


@pytest.mark.parametrize('status', ['ready', 'refused', 'cancelled'])
def test_handoff_is_single_request_and_never_retries(tmp_path, monkeypatch, status):
    monkeypatch.setattr(flow, 'validate', lambda *_: None)
    def launch(file):
        body = json.loads(file.read_text())
        assert body['project'] == URL and body['profile'] == 'principal'
        assert not any(k in body for k in ('password','cookie','token'))
        if status == 'ready':
            Image.new('RGB', (64,64), 'blue').save(file.with_suffix('.png'))
        file.with_suffix('.result.json').write_text(json.dumps({'status':status}))
        return Mock()
    launcher = Mock(side_effect=launch)
    monkeypatch.setattr(flow, '_launch', launcher)
    if status == 'ready':
        assert flow.generate('A historical illustration', tmp_path, 'principal', URL).is_file()
    else:
        with pytest.raises(flow.FlowError):
            flow.generate('A historical illustration', tmp_path, 'principal', URL)
    assert launcher.call_count == 1


def test_download_is_decoded_not_trusted_by_extension(tmp_path):
    def save(path):
        Path(path).write_text('not an image')
    with pytest.raises(Exception):
        flow._save_image(Mock(save_as=save), tmp_path/'image.png')
    assert not (tmp_path/'image.png').exists()
    assert not (tmp_path/'image.download').exists()


@pytest.mark.parametrize('name', ['giliard', ' giliard ', '\u200bgiliard\ufeff', '\tgiliard\n'])
def test_profile_boundary_whitespace_is_normalized_before_launch(tmp_path, monkeypatch, name):
    monkeypatch.setattr(flow, '_root', lambda: tmp_path)
    monkeypatch.setattr(flow.importlib.util, 'find_spec', lambda *_: object())
    launcher=Mock()
    monkeypatch.setattr(flow, '_launch', launcher)
    flow.connect(name, ' '+URL+' ')
    request=launcher.call_args.args[0]
    body=json.loads(request.read_text())
    assert body['profile']=='giliard' and body['project']==URL
    assert body['action']=='connect'


def test_standalone_test_launches_one_image_without_video_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, '_root', lambda: tmp_path)
    monkeypatch.setattr(flow.importlib.util, 'find_spec', lambda *_: object())
    launcher=Mock()
    monkeypatch.setattr(flow, '_launch', launcher)
    request=flow.start_test(' giliard ',URL,True)
    body=json.loads(request.read_text())
    assert body['profile']=='giliard' and body['action']=='generate'
    assert body['timeout']==180 and body['require_zero'] is True
    assert 'prompt' in body
    assert launcher.call_count==1


def test_login_uses_regular_chrome_without_automation_port(tmp_path,monkeypatch):
    monkeypatch.setattr(flow,'validate',lambda *_:None)
    monkeypatch.setattr(flow,'_root',lambda:tmp_path)
    monkeypatch.setattr(flow,'_chrome_executable',lambda:'chrome.exe')
    process=Mock()
    process.poll.return_value=0
    launch=Mock(return_value=process)
    monkeypatch.setattr(flow.subprocess,'Popen',launch)
    request=tmp_path/'connect.json'
    request.write_text(json.dumps({'profile':'giliard','project':URL,'action':'connect'}))
    flow._browser(request)
    args=launch.call_args.args[0]
    assert args[0]=='chrome.exe'
    assert not any('remote-debugging' in arg or 'no-sandbox' in arg or 'disable-blink' in arg for arg in args)
    assert '--user-data-dir='+str(tmp_path/'profiles'/'giliard') in args
    assert json.loads(request.with_suffix('.result.json').read_text())['status']=='closed'
    process.wait.assert_called_once()


def test_submitted_unknown_result_is_never_reposted(tmp_path,monkeypatch):
    monkeypatch.setattr(flow,'validate',lambda *_:None)
    def lost(request):
        request.with_suffix('.submitted.json').write_text(json.dumps({'submitted':True}))
        return Mock()
    launcher=Mock(side_effect=lost)
    monkeypatch.setattr(flow,'_launch',launcher)
    for _ in range(2):
        with pytest.raises(flow.FlowError):flow.generate('Test scene',tmp_path,'principal',URL)
    launcher.assert_called_once()


def test_ready_image_is_reused_without_another_browser_launch(tmp_path,monkeypatch):
    monkeypatch.setattr(flow,'validate',lambda *_:None)
    def ready(request):
        Image.new('RGB',(320,180),'blue').save(request.with_suffix('.png'))
        request.with_suffix('.result.json').write_text(json.dumps({'status':'ready','submitted':True}))
        return Mock()
    launcher=Mock(side_effect=ready)
    monkeypatch.setattr(flow,'_launch',launcher)
    first=flow.generate('Test scene',tmp_path,'principal',URL)
    assert flow.generate('Test scene',tmp_path,'principal',URL)==first
    launcher.assert_called_once()


def test_failed_controls_before_submission_can_be_retried_explicitly(tmp_path,monkeypatch):
    monkeypatch.setattr(flow,'validate',lambda *_:None)
    def blocked(request):
        request.with_suffix('.result.json').write_text(json.dumps({'status':'failed','submitted':False,'error':'control missing'}))
        return Mock()
    launcher=Mock(side_effect=blocked)
    monkeypatch.setattr(flow,'_launch',launcher)
    for _ in range(2):
        with pytest.raises(flow.FlowError):flow.generate('Test scene',tmp_path,'principal',URL)
    assert launcher.call_count==2  # Neither attempt submitted a generation.


def test_devtools_waits_for_initially_empty_port_file(tmp_path,monkeypatch):
    port=tmp_path/'DevToolsActivePort'
    port.write_text('')
    chrome=Mock()
    chrome.poll.return_value=None
    def complete(_):port.write_text('9222\n/devtools/browser/test\n')
    monkeypatch.setattr(flow.time,'sleep',complete)
    assert flow._wait_devtools(chrome,port,timeout=2)=='9222'


def test_diagnostic_records_stage_and_submission_without_exception_message(tmp_path):
    page=Mock()
    page.url='https://flow.google.com/project/test'
    page.evaluate.return_value=[{'tag':'BUTTON','label':'Nano Banana 2.1 x2'}]
    request=tmp_path/'flow-request.json'
    flow._diagnostic(request,page,'selecionando_imagem',RuntimeError('secret-token'),False)
    data=json.loads(request.with_suffix('.diagnostic.json').read_text())
    assert data['stage']=='selecionando_imagem' and data['submitted'] is False
    assert data['exception_type']=='RuntimeError'
    assert 'secret-token' not in json.dumps(data)


def test_flow_errors_are_identical_when_worker_module_is_executed_separately():
    import runpy
    namespace=runpy.run_path(str(Path(flow.__file__)),run_name='flow_worker_test')
    assert namespace['FlowError'] is flow.FlowError
    assert namespace['FlowRefusal'] is flow.FlowRefusal


@pytest.mark.parametrize('action',['generate','inspect'])
def test_separate_worker_preserves_real_error_or_inspects_without_sending(tmp_path,monkeypatch,action):
    import runpy
    from unittest.mock import MagicMock,patch
    namespace=runpy.run_path(str(Path(flow.__file__)),run_name='flow_worker_test')
    worker=namespace['_browser']
    scope=worker.__globals__
    scope['validate']=lambda *_:None
    scope['_root']=lambda:tmp_path
    scope['_chrome_executable']=lambda:'chrome.exe'
    scope['_wait_devtools']=lambda *_:'9222'
    page=MagicMock()
    page.url=URL
    page.locator.return_value.inner_text.return_value='Não foi possível concluir a geração.'
    page.evaluate.return_value=[]
    context=MagicMock()
    context.pages=[page]
    browser=MagicMock()
    browser.contexts=[context]
    p=MagicMock()
    p.chromium.connect_over_cdp.return_value=browser
    manager=MagicMock()
    manager.__enter__.return_value=p
    process=MagicMock()
    process.poll.return_value=0
    request=tmp_path/'flow-request.json'
    request.write_text(json.dumps({'profile':'principal','project':URL,'action':action,'prompt':'test'}))
    def fail(*args,**kwargs):
        kwargs['on_stage']('aguardando_imagem')
        raise flow.FlowError('Flow generation result timed out. Review project before another request.')
    with patch.object(flow.subprocess,'Popen',return_value=process),patch('playwright.sync_api.sync_playwright',return_value=manager),patch('app.services.flow_automation.generate',side_effect=fail) as generate:
        worker(request)
    result=json.loads(request.with_suffix('.result.json').read_text())
    diagnostic=json.loads(request.with_suffix('.diagnostic.json').read_text())
    if action=='generate':
        assert 'generation result timed out' in result['error']
        assert result['stage']=='aguardando_imagem'
        assert diagnostic['reason'].startswith('Flow generation result timed out')
        generate.assert_called_once()
    else:
        assert result['status']=='inspected' and result['submitted'] is False
        assert diagnostic['visible_messages']==['Não foi possível concluir a geração.']
        generate.assert_not_called()
    browser.close.assert_called_once()


def test_read_only_inspection_uses_recorded_project_without_new_generation(tmp_path,monkeypatch):
    monkeypatch.setattr(flow,'_root',lambda:tmp_path)
    monkeypatch.setattr(flow,'validate',lambda *_:None)
    previous=tmp_path/'tests'/'previous'/'flow-request.json'
    previous.parent.mkdir(parents=True)
    previous.write_text(json.dumps({'action':'generate','profile':'principal','project':URL,'prompt':'private prompt'}))
    launcher=Mock()
    monkeypatch.setattr(flow,'_launch',launcher)
    request=flow.start_inspection('principal','https://flow.google.com/project/11111111-1111-1111-1111-111111111111',use_latest_test=True)
    data=json.loads(request.read_text())
    assert data=={'action':'inspect','profile':'principal','project':URL}
    assert 'prompt' not in data
    launcher.assert_called_once()
    assert flow.latest_test('principal')[1]==previous
