import io
import json
from pathlib import Path
from unittest.mock import Mock,patch
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app.models.schema import VideoParams
from app.services.historical_archive.contracts import ArchiveCandidate,ArchiveSettings,ArchiveError,ArchiveDisabled,ArchivePending
from app.services.historical_archive.service import HistoricalArchiveService,paths
from app.services.historical_archive.rights import assess
from app.services.historical_archive.query_builder import build
from app.services.historical_archive.ranker import rank
from app.services.historical_archive.downloader import download,local
from app.services.historical_archive.network import Transport,safe_url
from app.services.historical_archive.providers.loc import LOCProvider
from app.services.historical_archive.providers.nara import NARAProvider
from app.services.historical_archive.providers.wikimedia import WikimediaProvider
from app.services.historical_archive import network,settings


def png(color='blue'):
    out=io.BytesIO();Image.new('RGB',(160,100),color).save(out,format='PNG');return out.getvalue()


def candidate(**values):
    base=dict(provider='loc',record_id='record1',title='K-129 Soviet submarine 1968',description='Pacific fleet Soviet submarine',date_created='1968',
        creator='Photographer',institution='Archive',source_url='https://www.loc.gov/item/123/',download_url='https://tile.loc.gov/image.jpg',
        rights_statement='Public domain',attribution='Photographer — Archive — K-129',metadata={'width':1600,'authenticity':'archive_record_not_ai'})
    base.update(values);return ArchiveCandidate(**base)


SCENE={'id':1,'text':'The Soviet submarine K-129 disappeared in 1968.','search_query':'Soviet submarine K-129 1968',
       'location':'Pacific','start_frame':0,'end_frame':30}


@pytest.fixture
def setup(tmp_path,monkeypatch):
    from app.utils import utils
    monkeypatch.setattr(utils,'storage_dir',lambda sub_dir='',create=False:str(tmp_path/sub_dir))
    prefs={'historical_archive_enabled':True,'historical_archive_min_score':0}
    transport=Mock()
    transport.settings=ArchiveSettings(enabled=True)
    transport.get.return_value=png()
    provider=Mock(name='provider');provider.name='loc';provider.search.return_value=[candidate()]
    factory=Mock(return_value=[provider])
    service=HistoricalArchiveService('project1',lambda:prefs,factory,transport)
    return service,prefs,provider,factory,transport


def test_default_off_has_zero_providers_network_or_directories(tmp_path,monkeypatch):
    from app.utils import utils
    monkeypatch.setattr(utils,'storage_dir',lambda *args,**kwargs:str(tmp_path))
    factory=Mock()
    service=HistoricalArchiveService('project1',lambda:{},factory)
    assert not ArchiveSettings().enabled
    assert service.search_scene(SCENE) is None
    assert service.select(SCENE)==(None,None)
    assert service.health_check()=={'status':'disabled'}
    factory.assert_not_called()
    assert list(tmp_path.iterdir())==[]


def test_enabled_scene_search_deduplicates_and_resume_reuses_saved_data(setup):
    service,prefs,provider,_,transport=setup
    entry=service.search_scene(SCENE)
    assert len(entry['candidates'])==1
    assert entry['candidates'][0]['rights_status']=='rights_cleared'
    count=provider.search.call_count
    assert service.search_scene(SCENE)==entry
    assert provider.search.call_count==count
    transport.get.assert_not_called()


def test_disable_mid_provider_stops_new_searches_without_deleting_results(setup):
    service,prefs,provider,factory,transport=setup
    def turn_off(*args):prefs['historical_archive_enabled']=False;return [candidate()]
    provider.search.side_effect=turn_off
    entry=service.search_scene(SCENE)
    assert provider.search.call_count==1
    assert entry['status']=='cancelled'
    assert service.select(SCENE)==(None,None)
    transport.get.assert_not_called()
    assert (service.folder/'manifest.json').exists()
    assert prefs['historical_archive_min_score']==0


def test_provider_outage_and_missing_key_do_not_stop_other_sources(setup):
    service,_,provider,factory,_=setup
    unavailable=Mock();unavailable.name='nara';unavailable.search.side_effect=ArchiveError('Needs API key')
    factory.return_value=[unavailable,provider]
    entry=service.search_scene(SCENE)
    assert entry['candidates']
    assert service.snapshot()['providers']['nara']['status']=='unavailable'
    assert service.snapshot()['providers']['loc']['status']=='available'


@pytest.mark.parametrize('rights,url,expected',[
    ('','', 'needs_review'),('No known restrictions on publication','', 'needs_review'),('Unrestricted','', 'needs_review'),
    ('Public domain','', 'rights_cleared'),('Not in the public domain','', 'restricted'),('All rights reserved','', 'restricted'),
    ('CC BY-NC','https://creativecommons.org/licenses/by-nc/4.0/','restricted'),
    ('CC BY-SA','https://creativecommons.org/licenses/by-sa/4.0/','rights_cleared'),
    ('CC0','https://creativecommons.org/publicdomain/zero/1.0/','rights_cleared'),
    ('','https://fake.example/licenses/by/4.0/','needs_review'),
    ('Possibly public domain','', 'needs_review')])
def test_rights_are_independent_of_archive_host(rights,url,expected):
    assert assess(candidate(rights_statement=rights,license_url=url))[0]==expected


def test_cc_attribution_missing_requires_review():
    assert assess(candidate(rights_statement='CC BY',license_url='https://creativecommons.org/licenses/by/4.0/',creator=''))[0]=='needs_review'


def test_download_only_cleared_and_credits_only_after_use(setup):
    service,_,_,_,transport=setup
    path,provenance=service.select(SCENE)
    assert Path(path).exists()
    data=service.snapshot();item=data['scenes']['scene_001']['candidates'][0]
    assert item['state']=='downloaded' and not item['used']
    assert 'K-129' not in (service.folder/'sources_and_credits.md').read_text()
    service.mark_used(provenance)
    credits=(service.folder/'sources_and_credits.md').read_text()
    assert 'K-129' in credits and 'https://www.loc.gov/item/123/' in credits
    count=transport.get.call_count
    assert service.select(SCENE)[0]==path
    assert transport.get.call_count==count


def test_unknown_rights_are_skipped_without_approval_or_download(setup):
    service,prefs,provider,_,transport=setup
    provider.search.return_value=[candidate(rights_statement='')]
    assert service.select(SCENE)==(None,None)
    item=service.snapshot()['scenes']['scene_001']['candidates'][0]
    assert item['state']=='skipped_unknown_rights'
    assert service.download_item(1,item['id'])==(None,None)
    transport.get.assert_not_called()
    assert not hasattr(service,'decide')


def test_restricted_item_is_skipped_without_approval_workflow(setup):
    service,_,provider,_,transport=setup
    provider.search.return_value=[candidate(rights_statement='All rights reserved')]
    assert service.select(SCENE)==(None,None)
    transport.get.assert_not_called()


def test_research_only_never_downloads(setup):
    service,prefs,_,_,transport=setup
    prefs['historical_archive_mode']='historical_research_only'
    assert service.select(SCENE)==(None,None)
    assert service.snapshot()['scenes']
    transport.get.assert_not_called()


@pytest.mark.parametrize('legacy_mode',['manual_review','historical_first'])
def test_old_modes_do_not_introduce_approval_gates(setup,legacy_mode):
    service,prefs,provider,_,transport=setup
    prefs['historical_archive_mode']=legacy_mode
    provider.search.return_value=[candidate(rights_statement='')]
    assert service.settings().mode=='historical_plus_stock'
    assert service.select(SCENE)==(None,None)
    transport.get.assert_not_called()


def test_budget_global_across_chapters_and_no_duplicate_consecutive_asset(setup):
    service,prefs,provider,factory,transport=setup
    prefs['historical_archive_max_downloads_per_video']=1
    path,provenance=service.select(SCENE);service.mark_used(provenance)
    chapter=HistoricalArchiveService('project1/chapters/001',lambda:prefs,factory,transport)
    assert chapter.folder==service.folder
    assert chapter.select({**SCENE,'id':2})==(None,None)
    assert transport.get.call_count==1


@pytest.mark.parametrize('content',[b'',b'<html>not an image</html>',b'fake jpeg'])
def test_corrupt_or_html_download_is_rejected(setup,content):
    service,_,_,_,transport=setup
    transport.get.return_value=content
    assert service.select(SCENE)==(None,None)
    assert not list(service.folder.rglob('*.partial'))
    assert not list(service.folder.rglob('*.png'))


@pytest.mark.parametrize('url',['http://www.loc.gov/item/1','https://127.0.0.1/a','https://www.loc.gov.evil.test/a',
    'https://www.loc.gov:444/a','https://secret@www.loc.gov/a','file:///tmp/test'])
def test_untrusted_urls_and_paths_rejected(url,tmp_path):
    with pytest.raises(ArchiveError):safe_url(url)
    with pytest.raises(ArchiveError):local(tmp_path,'../outside')
    with pytest.raises(ArchiveError):paths('../outside')


def test_cancellation_and_toggle_off_prevent_download(setup):
    service,prefs,_,_,transport=setup
    service.search_scene(SCENE)
    prefs['historical_archive_enabled']=False
    assert service.select(SCENE)==(None,None)
    transport.get.assert_not_called()
    prefs['historical_archive_enabled']=True;service.cancel()
    assert service.select(SCENE)==(None,None)


def test_conflicting_equipment_or_dates_not_auto_selected(setup):
    service,_,provider,_,transport=setup
    provider.search.return_value=[candidate(title='Soviet submarine K-219 1986',date_created='1986')]
    assert service.select(SCENE)==(None,None)
    transport.get.assert_not_called()


def test_query_dates_are_not_invented():
    query=build({'text':'A Soviet submarine in the Pacific','id':1},ArchiveSettings())
    assert query['dates']==[] and query['confidence']=='low'
    assert build(SCENE,ArchiveSettings())['dates']==['1968']


def test_network_cache_off_gate_and_retry_after(tmp_path,monkeypatch):
    monkeypatch.setattr(network,'_NEXT',{})
    active=[True]
    transport=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:active[0])
    transport.pause=Mock()
    response=Mock(status_code=200,headers={})
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
    response.iter_content.return_value=[b'{"results":[]}']
    with patch.object(network.requests,'get',return_value=response) as get:
        assert transport.json('loc','https://www.loc.gov/search/',params={'q':'test'})=={'results':[]}
        transport.json('loc','https://www.loc.gov/search/',params={'q':'test'})
        get.assert_called_once()
        active[0]=False
        with pytest.raises(ArchiveDisabled):transport.json('loc','https://www.loc.gov/search/',params={'q':'test'})
        assert get.call_count==1
        active[0]=True;response.status_code=429;response.headers={'Retry-After':'120'}
        with pytest.raises(ArchiveError,match='Rate limit'):transport.get('loc','https://www.loc.gov/search/')
        with pytest.raises(ArchiveError,match='espera'):transport.get('loc','https://www.loc.gov/search/')
        assert get.call_count==2


def test_provider_normalization_and_original_metadata():
    api=Mock()
    api.json.side_effect=[{'results':[{'id':'https://www.loc.gov/item/123/','title':'Map'}]},
        {'item':{'title':'Map 1968','date':'1968','original_format':['map'],'rights_advisory':['Public domain']},
         'resources':[{'files':[[{'url':'https://tile.loc.gov/map.jpg','mimetype':'image/jpeg','width':2000}]]}]}]
    loc=LOCProvider(api).search('map 1968',['map'],3)[0]
    assert loc.institution=='Library of Congress' and loc.media_type=='map'
    assert loc.metadata['record']['date']=='1968' and loc.download_url.endswith('map.jpg')
    api.json.side_effect=None
    api.json.return_value={'body':{'hits':{'hits':[{'_source':{'record':{'naId':123,'title':'K-129',
        'useRestriction':{'status':{'termName':'Unrestricted'}},'digitalObjects':[{'objectUrl':'https://catalog.archives.gov/photo.jpg','objectId':7}]}}}]}}}
    nara=NARAProvider(api,'test-secret').search('K-129',['photograph'],3)[0]
    assert nara.source_url.endswith('/123') and assess(nara)[0]=='needs_review'
    assert api.json.call_args.kwargs['headers']=={'x-api-key':'test-secret'}
    api.json.return_value={'query':{'pages':{'4':{'pageid':4,'title':'File:K-129.jpg','imageinfo':[{
        'url':'https://upload.wikimedia.org/a.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:K-129.jpg','width':1000,
        'extmetadata':{'LicenseShortName':{'value':'CC BY-SA 4.0'},'LicenseUrl':{'value':'https://creativecommons.org/licenses/by-sa/4.0/'},'Artist':{'value':'<b>Photographer</b>'}}}]}}}}
    commons=WikimediaProvider(api).search('K-129',['photograph'],3)[0]
    assert commons.creator=='Photographer' and assess(commons)[0]=='rights_cleared'
    assert commons.metadata['record']['pageid']==4
    assert NARAProvider(api).health_check()=={'status':'needs_api_key'}


def test_settings_ui_off_never_calls_sources_or_asks_for_keys(monkeypatch):
    values={}
    monkeypatch.setattr(settings,'mapping',lambda:values)
    def save(section,key,value):values[key]=value
    with patch.object(HistoricalArchiveService,'health_check') as health,patch.object(HistoricalArchiveService,'search_scene') as search:
        app=AppTest.from_string('from webui.historical_archive_settings import render\nrender(lambda *args: None)').run()
        assert not app.exception
        assert not app.toggle(key='haf_enabled').value
        assert app.checkbox(key='haf_loc').disabled
        assert app.text_input(key='haf_nara_key').proto.type==1
        health.assert_not_called();search.assert_not_called()


@pytest.mark.parametrize('aspect', ['16:9','9:16'])
def test_archive_source_renders_real_horizontal_and_vertical_video(setup,tmp_path,aspect,monkeypatch):
    from app.services import mixed_materials as mixed
    from app.services.historical_archive.pipeline import visual_source,render_params
    from app.models.schema import ImageMotion
    from moviepy import VideoFileClip
    service,_,_,_,_=setup
    path,provenance=service.select(SCENE)
    # Keep render dimensions small while exercising real ffmpeg fitting and frame count.
    monkeypatch.setattr(mixed.VideoAspect,'to_resolution',lambda self: (160,90) if self.value=='16:9' else (90,160))
    params=VideoParams(video_subject='K-129',video_aspect=aspect,image_motion=ImageMotion.static)
    scene={**SCENE,'end_frame':9}
    source=visual_source(path,scene,params,service)
    output=tmp_path/('render-'+aspect.replace(':','-')+'.mp4')
    mixed.render(source,output,9,render_params(params,service))
    with VideoFileClip(str(output)) as clip:
        assert tuple(clip.size)==((160,90) if aspect=='16:9' else (90,160))
        assert abs(clip.duration-.3)<.05
        clip.get_frame(.1)
    service.mark_used(provenance)
    assert len(json.loads((service.folder/'sources_and_credits.json').read_text()))==1


def test_legacy_adapter_off_and_research_only_preserve_existing_sources(setup,monkeypatch):
    from app.services.historical_archive import pipeline
    service,prefs,_,_,transport=setup
    monkeypatch.setattr(pipeline,'HistoricalArchiveService',lambda *a:service)
    fallback=Mock(return_value=['existing.mp4'])
    params=VideoParams(video_subject='K-129',video_source='pexels')
    prefs['historical_archive_enabled']=False
    assert pipeline.prepare_legacy('project1',params,SCENE['text'],2,'',[],fallback)==['existing.mp4']
    assert not params.historical_archive_prepared
    prefs['historical_archive_enabled']=True;prefs['historical_archive_mode']='historical_research_only'
    assert pipeline.prepare_legacy('project1',params,SCENE['text'],2,'',[],fallback)==['existing.mp4']
    transport.get.assert_not_called()


def test_live_toggle_and_provider_preferences_persist_in_ui(monkeypatch):
    values={}
    monkeypatch.setattr(settings,'mapping',lambda:values)
    # The actual persistence adapter is substituted; controls retain their state on OFF.
    import webui.historical_archive_settings as ui
    monkeypatch.setattr(ui,'render',ui.render)
    with patch.object(HistoricalArchiveService,'health_check') as health:
        script='''
import streamlit as st
from webui.historical_archive_settings import render
if 'haf_values' not in st.session_state:st.session_state.haf_values={}
def save(section,key,value):st.session_state.haf_values[key]=value
render(save)
'''
        app=AppTest.from_string(script).run()
        app.toggle(key='haf_enabled').set_value(True).run()
        app.checkbox(key='haf_nara').set_value(False).run()
        assert not app.session_state.haf_values['historical_archive_nara_enabled']
        app.toggle(key='haf_enabled').set_value(False).run()
        assert not app.session_state.haf_values['historical_archive_enabled']
        assert not app.checkbox(key='haf_nara').value and app.checkbox(key='haf_nara').disabled
        health.assert_not_called()


def test_transient_backoff_bounded_and_no_redirects(tmp_path,monkeypatch):
    monkeypatch.setattr(network,'_NEXT',{})
    transport=Transport(tmp_path,ArchiveSettings(enabled=True,max_retries=1),lambda:True)
    transport.pause=Mock()
    def response(code):
        r=Mock(status_code=code,headers={});r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=None);r.iter_content.return_value=[b'{}'];return r
    with patch.object(network.requests,'get',side_effect=[response(503),response(200)]) as get:
        assert transport.get('loc','https://www.loc.gov/search/')==b'{}'
        assert get.call_count==2
        assert get.call_args.kwargs['allow_redirects'] is False


def test_resume_audio_hash_and_completed_project_guard(setup,monkeypatch):
    from app.services.historical_archive import pipeline
    service,_,_,_,_=setup
    directory=service.folder.parent;directory.mkdir(parents=True)
    audio=directory/'audio.mp3';audio.write_bytes(b'original')
    params=VideoParams(video_subject='K-129',video_source='pexels')
    pipeline.save_resume_context('project1',params,SCENE['text'],[],str(audio),'',2)
    assert pipeline.load_resume('project1')['params'].historical_archive_resume
    audio.write_bytes(b'changed')
    with pytest.raises(ArchiveError,match='alterado'):pipeline.load_resume('project1')
    (directory/'final-1.mp4').write_bytes(b'finished')
    with pytest.raises(ArchiveError,match='concluído'):pipeline.load_resume('project1')


@pytest.mark.parametrize('statement', ['Public domain status not established','Not necessarily public domain','Public domain in the US only','May be in the public domain'])
def test_mentions_of_public_domain_are_not_permissions(statement):
    assert assess(candidate(rights_statement=statement))[0]=='needs_review'


def test_nara_local_monthly_budget_does_not_expose_key(tmp_path,monkeypatch):
    monkeypatch.setattr(network,'_NEXT',{})
    transport=Transport(tmp_path,ArchiveSettings(enabled=True,nara_monthly_limit=1),lambda:True)
    transport.pause=Mock()
    response=Mock(status_code=200,headers={});response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
    response.iter_content.return_value=[b'{}']
    with patch.object(network.requests,'get',return_value=response) as get:
        transport.get('nara','https://catalog.archives.gov/api/v2/records/search',headers={'x-api-key':'secret-not-logged'})
        with pytest.raises(ArchiveError,match='mensal'):transport.get('nara','https://catalog.archives.gov/api/v2/records/search')
        get.assert_called_once()
    assert all('secret-not-logged' not in file.read_text() for file in tmp_path.glob('*.json'))


def test_inflight_disable_discards_download_without_a_saved_file(tmp_path):
    from app.services.historical_archive.downloader import download
    active=[True]
    transport=Transport(tmp_path/'cache',ArchiveSettings(enabled=True),lambda:active[0])
    response=Mock(status_code=200,headers={});response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
    def chunks(*args):
        active[0]=False
        yield png()
    response.iter_content.side_effect=chunks
    with patch.object(network.requests,'get',return_value=response):
        with pytest.raises(ArchiveDisabled):download(candidate(),tmp_path/'approved',transport)
    assert not (tmp_path/'approved').exists()


def test_commons_document_uses_api_designated_raster_preview():
    api=Mock()
    api.json.return_value={'query':{'pages':{'1':{'pageid':1,'title':'File:Historical map.svg','imageinfo':[{
        'mime':'image/svg+xml','url':'https://upload.wikimedia.org/original.svg','thumburl':'https://upload.wikimedia.org/thumb.png',
        'descriptionurl':'https://commons.wikimedia.org/wiki/File:Historical_map.svg',
        'extmetadata':{'LicenseShortName':{'value':'Public domain'}}}]}}}}
    result=WikimediaProvider(api).search('historical map',['map'],1)[0]
    assert result.download_url.endswith('thumb.png')
    assert result.metadata['original_file_url'].endswith('original.svg')
    assert 'preview' in result.metadata['download_variant']


def test_unsourced_planner_dates_and_equipment_not_promoted_to_queries():
    query=build({'id':1,'text':'A submarine disappeared at sea.','search_query':'K-129 submarine 1968','period':'1968'},ArchiveSettings())
    assert query['dates']==[]
    assert all('1968' not in q and 'K-129' not in q for q in query['queries'])


def test_ai_annotated_archive_candidate_is_skipped_automatically(setup):
    service,_,provider,_,transport=setup
    provider.search.return_value=[candidate(metadata={'ai_generated':True})]
    assert service.select(SCENE)==(None,None)
    assert service.snapshot()['scenes']['scene_001']['candidates'][0]['state']=='skipped_unknown_rights'
    transport.get.assert_not_called()


def test_archival_footage_is_validated_and_downloaded_by_content(setup,tmp_path):
    import subprocess
    from app.utils import utils
    service,_,_,_,transport=setup
    video=tmp_path/'fixture.mp4'
    result=subprocess.run([utils.get_ffmpeg_binary(),'-v','error','-f','lavfi','-i','color=c=blue:s=160x90:d=0.2','-c:v','libx264','-pix_fmt','yuv420p','-y',str(video)],capture_output=True)
    assert result.returncode==0
    transport.get.return_value=video.read_bytes()
    file,digest=download(candidate(media_type='video'),tmp_path/'approved',transport)
    assert file.suffix=='.mp4' and digest


def test_legacy_archive_adapter_assembles_timed_scenes_without_approvals(setup,tmp_path,monkeypatch):
    from app.services.historical_archive import pipeline
    from app.services import mixed_materials as mixed
    from app.models.schema import ImageMotion
    from moviepy import VideoFileClip
    service,_,_,_,_=setup
    monkeypatch.setattr(pipeline,'HistoricalArchiveService',lambda *a:service)
    monkeypatch.setattr(mixed.VideoAspect,'to_resolution',lambda self:(160,90))
    params=VideoParams(video_subject='K-129',video_source='pexels',video_aspect='16:9',image_motion=ImageMotion.static)
    fallback=Mock()
    outputs=pipeline.prepare_legacy('project1',params,SCENE['text'],.4,'',[],fallback)
    assert params.historical_archive_prepared and len(outputs)==1
    fallback.assert_not_called()
    combined=tmp_path/'combined.mp4'
    mixed.join(outputs,combined)
    with VideoFileClip(str(combined)) as clip:
        assert tuple(clip.size)==(160,90)
        assert abs(clip.duration-.4)<.05
    assert json.loads((service.folder/'sources_and_credits.json').read_text())


def test_loc_legacy_http_identifiers_upgrade_only_official_host():
    api=Mock()
    api.json.side_effect=[{'results':[{'id':'http://www.loc.gov/item/123/','title':'Map'}]},
        {'item':{'title':'Map','original_format':['map'],'image_url':['http://tile.loc.gov/map.jpg'],'rights_advisory':['Public domain']}}]
    item=LOCProvider(api).search('map',['map'],1)[0]
    assert item.source_url=='https://www.loc.gov/item/123/'
    assert item.download_url=='https://tile.loc.gov/map.jpg'
    assert item.metadata['search_result']['id'].startswith('http:')


@pytest.mark.parametrize('provider_name',['loc','nara','wikimedia'])
def test_optional_live_official_archive_api(provider_name,tmp_path):
    import os
    if os.environ.get('MPT_ARCHIVE_LIVE_TESTS')!='1':pytest.skip('Opt-in real API test; no calls in normal suite')
    key=os.environ.get('NARA_API_KEY','')
    if provider_name=='nara' and not key:pytest.skip('NARA_API_KEY not configured')
    transport=Transport(tmp_path,ArchiveSettings(enabled=True,max_retries=0),lambda:True)
    provider={'loc':lambda:LOCProvider(transport),'nara':lambda:NARAProvider(transport,key),
              'wikimedia':lambda:WikimediaProvider(transport)}[provider_name]()
    results=provider.search('photograph',['photograph','document','map','video'],3)
    assert results and all(isinstance(item,ArchiveCandidate) and item.source_url for item in results)


def test_automatic_results_ui_has_no_approval_controls(setup,monkeypatch):
    service,prefs,provider,_,_=setup
    provider.search.return_value=[candidate(rights_statement='')]
    service.search_scene(SCENE)
    monkeypatch.setattr(settings,'mapping',lambda:prefs)
    app=AppTest.from_string('from webui.historical_archive_settings import render\nrender(lambda *args:None)').run()
    app.text_input(key='haf_task_id').set_value('project1').run()
    assert not app.exception
    assert not any('Aprovar' in item.label or 'Rejeitar' in item.label for item in app.button)
    assert not any('Conferi' in item.label for item in app.checkbox)


def test_disable_after_completed_download_preserves_checkpoint(setup,monkeypatch):
    service,prefs,_,_,_=setup
    from app.services.historical_archive import service as module
    from app.services.historical_archive.downloader import checksum
    def complete(candidate,folder,transport):
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/'retained.png';target.write_bytes(png())
        prefs['historical_archive_enabled']=False
        return target,checksum(target)
    monkeypatch.setattr(module,'download',complete)
    assert service.select(SCENE)==(None,None)
    item=service.snapshot()['scenes']['scene_001']['candidates'][0]
    assert item['state']=='downloaded' and (service.folder/item['downloaded_file']).exists()


def test_uncertain_high_score_does_not_crowd_out_a_cleared_match(setup):
    service,prefs,provider,factory,_=setup
    prefs['historical_archive_candidates_per_scene']=1
    provider.search.return_value=[candidate(rights_statement='')]
    usable=Mock();usable.name='wikimedia'
    usable.search.return_value=[candidate(provider='wikimedia',record_id='clear',title='K-129 submarine',description='',
        download_url='https://upload.wikimedia.org/submarine.jpg')]
    factory.return_value=[provider,usable]
    result=service.search_scene(SCENE)
    assert len(result['candidates'])==1
    assert result['candidates'][0]['candidate']['provider']=='wikimedia'
    assert service.select(SCENE)[0]
