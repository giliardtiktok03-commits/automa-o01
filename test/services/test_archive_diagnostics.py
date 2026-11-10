import io
import json
from unittest.mock import Mock,patch
from types import SimpleNamespace
from pathlib import Path
import pytest
from PIL import Image
from app.models.schema import VideoParams
from app.services import task,mixed_materials as mixed
from app.services.state import MemoryState
from app.services.historical_archive import settings,research_mode
from app.services.historical_archive.network import Transport
from app.services.historical_archive.diagnostics import DiagnosticRecorder
from app.services.historical_archive.service import HistoricalArchiveService

BASE='https://tile.loc.gov/image-services/iiif/service:example:page'
OCR='https://tile.loc.gov/files/page.alto.xml'
QUERY='Dust Bowl Farm Security Administration'


def response(body,status=200):
    r=Mock(status_code=status,headers={})
    r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=None)
    r.iter_content.return_value=[body]
    return r


@pytest.fixture
def env(tmp_path,monkeypatch):
    from app.utils import utils
    from app.services import state as sm
    prefs={'historical_archive_enabled':True,'historical_archive_mode':'historical_research_only',
           'historical_archive_loc_enabled':True,'historical_archive_nara_enabled':False,'historical_archive_wikimedia_enabled':False}
    monkeypatch.setattr(settings,'mapping',lambda:prefs)
    monkeypatch.setattr(utils,'storage_dir',lambda sub_dir='',create=False:str(tmp_path/sub_dir))
    monkeypatch.setattr(sm,'state',MemoryState())
    monkeypatch.setattr(Transport,'_loc_slot',lambda *args:None)
    monkeypatch.setattr(Transport,'pause',lambda *args:None)
    out=io.BytesIO();Image.new('RGB',(160,100),'blue').save(out,format='PNG')
    return prefs,out.getvalue(),tmp_path


def fake_loc(image,rights='Public domain',empty=False):
    def get(url,**kwargs):
        if '/search/' in url:return response(json.dumps({'results':[] if empty else [{'id':'https://www.loc.gov/item/123/'}]}).encode())
        if '/item/' in url:
            return response(json.dumps({'item':{'title':QUERY,'original_format':['manuscript'],'rights_advisory':rights,'image_url':[BASE+'/full/full/0/default.jpg']},
                'resources':[{'files':[[{'url':OCR,'mimetype':'application/alto+xml'}]]}]}).encode())
        if url.endswith('info.json'):return response(json.dumps({'@id':BASE,'width':2000,'height':1000,'profile':'http://iiif.io/api/image/2/level2.json'}).encode())
        if url==OCR:return response(b'<alto><TextLine><String CONTENT="Dust"/><String CONTENT="Bowl"/></TextLine></alto>')
        if '/full/' in url:return response(image)
        raise AssertionError('Unexpected request '+url)
    return get


def test_three_services_pass_without_generating_any_video_audio_or_stock(env):
    prefs,image,root=env
    params=VideoParams(video_subject=QUERY,video_source='mixed',mixed_use_grok=False,mixed_max_images=0)
    with patch('app.services.historical_archive.network.requests.get',side_effect=fake_loc(image)) as http,\
         patch.object(task,'generate_script') as script,patch.object(task,'generate_audio') as audio,\
         patch.object(task,'generate_subtitle') as subtitles,patch.object(task,'get_video_materials') as materials,\
         patch.object(task,'generate_final_videos') as video:
        result=task.start('research-test',params)
        assert result['historical_research_only'] and result['outcome']=='all_services_passed'
        for name in ('loc_json','loc_image','loc_text'):assert result['api_results'][name]['status']=='passed'
        assert result['api_results']['loc_json']['requests']==2
        assert result['api_results']['loc_image']['requests']==2
        assert result['api_results']['loc_text']['requests']==1
        for method in (script,audio,subtitles,materials,video):method.assert_not_called()
        assert all('.loc.gov/' in call.args[0] for call in http.call_args_list)
    assert not list(root.rglob('*.mp4'))
    assert not list(root.rglob('*.mp3'))
    assert not list(root.rglob('*.png'))  # diagnostic preview exists in memory, not material storage
    assert list(root.rglob('*.ocr.txt'))


def test_empty_search_is_http_pass_but_not_material_success(env):
    _,image,_=env
    with patch('app.services.historical_archive.network.requests.get',side_effect=fake_loc(image,empty=True)):
        result=research_mode.run('empty-test',VideoParams(video_subject=QUERY),loc_only=True)
    assert result['candidates']==0
    assert result['api_results']['loc_json']['status']=='passed'
    assert result['api_results']['loc_json']['search_results']==0
    assert result['api_results']['loc_image']['status']=='not_tested'
    assert result['api_results']['loc_text']['status']=='not_tested'
    assert result['outcome']!='all_services_passed'


def test_rights_unknown_are_not_approved_to_make_probe_green(env):
    _,image,_=env
    with patch('app.services.historical_archive.network.requests.get',side_effect=fake_loc(image,rights='No known restrictions')) as http:
        result=research_mode.run('rights-test',VideoParams(video_subject=QUERY),loc_only=True)
    assert http.call_count==2
    assert result['api_results']['loc_image']['status']=='not_tested'
    service=HistoricalArchiveService('rights-test')
    item=service.snapshot()['scenes']['scene_001']['candidates'][0]
    assert item['rights_status']=='needs_review' and item['state']=='skipped_unknown_rights'


def test_proxy_denial_is_not_reported_as_an_origin_http_status(env):
    from requests.exceptions import ProxyError
    with patch('app.services.historical_archive.network.requests.get',side_effect=ProxyError('Tunnel 403 secret-key')) as http:
        result=research_mode.run('proxy-test',VideoParams(video_subject=QUERY),loc_only=True)
    http.assert_called_once()
    assert result['api_results']['loc_json']['status']=='failed'
    assert result['api_results']['loc_json']['http_statuses']==[]
    assert result['api_results']['loc_image']['status']=='not_tested'
    assert 'secret-key' not in Path(result['diagnostic_report']).read_text()


def test_request_diagnostic_redacts_credentials(tmp_path):
    from app.services.historical_archive.diagnostics import safe_request
    url=safe_request('https://user:secret@tile.loc.gov/text-services/x?token=secret&format=json',{'api_key':'secret','q':'Dust Bowl'})
    assert 'secret' not in url and 'Dust' in url
    recorder=DiagnosticRecorder(tmp_path,lambda:True)
    recorder.record('loc_json','search_results','passed',count=0,reason='zero results')
    recorder.record('loc_image','image_info','not_available',reason='No IIIF link')
    report=recorder.read()
    assert report['services']['loc_image']['status']=='not_tested'


def test_off_research_never_calls_an_api(env):
    prefs,_,root=env;prefs['historical_archive_enabled']=False
    with patch('app.services.historical_archive.network.requests.get') as http:
        result=task.start('disabled-test',VideoParams(video_subject=QUERY,video_source='historical_research'))
    assert result['failed_stage']=='historical_research'
    http.assert_not_called()


def test_loc_independent_button_exists_without_providers_or_audio(env):
    from streamlit.testing.v1 import AppTest
    with patch.object(research_mode,'submit_loc',return_value='loc-probe-ui') as submit:
        app=AppTest.from_string('from webui.historical_archive_settings import render\nrender(lambda *args:None)').run()
        assert not app.exception
        assert not app.button(key='haf_probe_start').disabled
        app.text_input(key='haf_probe_query').set_value(QUERY)
        app.button(key='haf_probe_start').click().run()
        assert not app.exception
        submit.assert_called_once_with(QUERY)
        assert app.session_state.haf_probe_id=='loc-probe-ui'


def test_diagnostics_explain_why_historical_candidate_not_delivered(env):
    _,image,_=env
    # Video-mode service selection is tested independently from the research route.
    values=dict(settings.mapping(),historical_archive_mode='historical_plus_stock')
    service=HistoricalArchiveService('no-rights-material',settings_getter=lambda:values)
    with patch('app.services.historical_archive.network.requests.get',side_effect=fake_loc(image,rights='No known restrictions')):
        assert service.select({'id':1,'text':QUERY,'search_query':QUERY})==(None,None)
    assert 'direitos não liberados' in service.explain(1)
    report=service.diagnostic().read()
    assert report['services']['loc_json']['status']=='passed'
    assert report['services']['selection']['selection_status']=='not_available'
