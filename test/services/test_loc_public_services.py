import io
import json
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from PIL import Image

from app.services.historical_archive.contracts import ArchiveSettings,ArchiveError,ArchiveDisabled
from app.services.historical_archive.network import Transport,loc_bucket
from app.services.historical_archive import network
from app.services.historical_archive.providers.loc import LOCProvider
from app.services.historical_archive.providers.loc_services import LOCImageService,LOCTextService,LOCMetadataService,parse_ocr

BASE='https://tile.loc.gov/image-services/iiif/service:sgp:example:page1'
TEXT='https://tile.loc.gov/text-services/word-coordinates-service?format=json&record=example'
ALTO=b'<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"><Layout><Page><TextLine><String CONTENT="Soviet"/><String CONTENT="submarine"/></TextLine></Page></Layout></alto>'


def response(status=200,body=b'{}',headers=None):
    r=Mock(status_code=status,headers=headers or {})
    r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=None)
    r.iter_content.return_value=[body]
    return r


def fake_clock(monkeypatch,transport):
    now=[1000.]
    clock=SimpleNamespace(time=lambda:now[0],monotonic=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
    monkeypatch.setattr(network,'time',clock)
    def pause(seconds):transport.check();now[0]+=max(0,seconds)
    transport.pause=pause
    return now


@pytest.mark.parametrize('bucket,url,rpm',[
    ('loc_json','https://www.loc.gov/search/',20),
    ('loc_image',BASE+'/info.json',150),
    ('loc_text',TEXT,150)])
def test_official_service_limits_no_bursts_and_no_auth(tmp_path,monkeypatch,bucket,url,rpm):
    transport=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:True)
    now=fake_clock(monkeypatch,transport)
    starts=[]
    def get(*args,**kwargs):starts.append(now[0]);return response()
    with patch.object(network.requests,'get',side_effect=get) as http:
        for _ in range(rpm+1):transport.get(bucket,url)
        assert starts[-1]-starts[0]>=60-.0001
        for start in starts:
            assert sum(start<=t<start+60-.0001 for t in starts)<=rpm
        assert http.call_args.kwargs['headers'].keys()=={'User-Agent'}
        assert http.call_args.kwargs['allow_redirects'] is False


def test_quota_shared_between_service_instances_and_retries_count(tmp_path,monkeypatch):
    transport=Transport(tmp_path,ArchiveSettings(enabled=True,max_retries=1),lambda:True)
    now=fake_clock(monkeypatch,transport)
    with patch.object(network.requests,'get',side_effect=[response(503),response(),response()]) as http:
        transport.get('loc','https://www.loc.gov/search/')
        second=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:True)
        second.pause=transport.pause
        second.get('loc','https://www.loc.gov/item/123/')
        assert now[0]>=1006
        assert http.call_count==3
    assert len(json.loads((tmp_path/'loc_json-rate.json').read_text())['requests'])==3


@pytest.mark.parametrize('code',[429,403,503])
def test_block_stops_all_loc_services_without_service_rotation(tmp_path,monkeypatch,code):
    transport=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:True)
    fake_clock(monkeypatch,transport)
    with patch.object(network.requests,'get',return_value=response(code,headers={'Retry-After':'120'})) as http:
        with pytest.raises(ArchiveError,match='bloqueio'):transport.get('loc','https://www.loc.gov/search/')
        for bucket,url in [('loc_image',BASE+'/info.json'),('loc_text',TEXT)]:
            with pytest.raises(ArchiveError,match='espera'):transport.get(bucket,url)
        http.assert_called_once()
    assert json.loads((tmp_path/'loc-cooldown.json').read_text())['until']==1120


def test_retry_after_http_date_is_preserved(tmp_path,monkeypatch):
    transport=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:True)
    fake_clock(monkeypatch,transport)
    with patch.object(network.requests,'get',return_value=response(429,headers={'Retry-After':'Thu, 01 Jan 1970 00:20:00 GMT'})):
        with pytest.raises(ArchiveError):transport.get('loc','https://www.loc.gov/search/')
    assert json.loads((tmp_path/'loc-cooldown.json').read_text())['until']==1200


def test_quotas_are_independent_and_selected_by_real_service_url():
    assert loc_bucket('loc',BASE+'/full/1000,/0/default.jpg')=='loc_image'
    assert loc_bucket('loc',TEXT)=='loc_text'
    assert loc_bucket('loc','https://tile.loc.gov/storage-services/page.alto.xml')=='loc_text'
    assert loc_bucket('loc_image','https://www.loc.gov/search/')=='loc_json'
    assert loc_bucket('loc','https://www.loc.gov/item/123/')=='loc_json'
    assert loc_bucket('wikimedia','https://commons.wikimedia.org/w/api.php')=='wikimedia'


def test_iiif_info_controls_size_and_never_upscales():
    api=Mock();api.settings=ArchiveSettings()
    api.json.return_value={'@id':BASE,'width':4000,'height':2000,'profile':['http://iiif.io/api/image/2/level2.json']}
    result=LOCImageService(api).prepare({'image_url':[BASE+'/full/full/0/default.jpg']})
    assert result['image_url']==BASE+'/full/2048,/0/default.jpg'
    api.json.assert_called_once_with('loc_image',BASE+'/info.json')
    api.json.return_value.update(width=600,height=400)
    assert '/full/600,/' in LOCImageService(api).prepare({'info':BASE+'/info.json'})['image_url']


def test_iiif_level_zero_uses_declared_size_and_rejects_unsupported_processing():
    api=Mock();api.settings=ArchiveSettings()
    api.json.return_value={'width':4000,'height':4000,'profile':'http://iiif.io/api/image/2/level0.json','maxWidth':1000,'sizes':[{'width':1000,'height':1000},{'width':2000,'height':2000}]}
    assert '/full/1000,1000/' in LOCImageService(api).prepare({'info':BASE+'/info.json'})['image_url']
    api.json.return_value['sizes']=[]
    with pytest.raises(ArchiveError,match='redimensionamento'):LOCImageService(api).prepare({'info':BASE+'/info.json'})


@pytest.mark.parametrize('raw,expected,format',[
    (ALTO,'Soviet submarine','alto_xml'),
    (b'{"words":{"Soviet":[1,2,3],"submarine":[2,3,4]}}','Soviet submarine','word_coordinates_json'),
    (b'<html><div class="ocr_page"><span class="ocrx_word">Soviet</span> submarine</div></html>','Soviet','hocr'),
    (b'Soviet submarine','Soviet submarine','text')])
def test_ocr_decodes_document_text_without_running_local_ocr(raw,expected,format):
    result=parse_ocr(raw,1000)
    assert expected in result['text'] and result['format']==format


@pytest.mark.parametrize('raw',[b'<html>Blocked</html>',b'<!DOCTYPE a [<!ENTITY e "bad">]><alto>&e;</alto>',b'',b'{"error":"blocked"}'])
def test_ocr_rejects_error_pages_and_entities(raw):
    with pytest.raises((ArchiveError,ValueError)):parse_ocr(raw,1000)


def test_ocr_uses_only_resource_links_and_caches_without_key(tmp_path,monkeypatch):
    transport=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:True)
    fake_clock(monkeypatch,transport)
    with patch.object(network.requests,'get',return_value=response(body=ALTO)) as http:
        svc=LOCTextService(transport)
        first=svc.extract({'files':[[{'mimetype':'application/alto+xml','url':'https://tile.loc.gov/files/page.alto.xml'}]]})
        second=svc.extract({'files':[[{'url':'https://tile.loc.gov/files/page.alto.xml'}]]})
        assert first['text']==second['text']=='Soviet submarine'
        http.assert_called_once()
    assert LOCTextService(transport).extract({'id':'book-with-no-ocr'})['status']=='not_available'


def test_replacement_connector_combines_public_metadata_iiif_and_text():
    api=Mock();api.settings=ArchiveSettings()
    record={'item':{'title':'Submarine document 1968','date':'1968','original_format':['manuscript'],'rights_advisory':'Public domain','image_url':[BASE+'/full/full/0/default.jpg']},
        'resources':[{'files':[[{'url':BASE+'/info.json','mimetype':'application/json'},
                                {'url':'https://tile.loc.gov/files/page.alto.xml','mimetype':'application/alto+xml'}]]}]}
    api.json.side_effect=[{'results':[{'id':'http://www.loc.gov/item/123/'}]},record,
                          {'@id':BASE,'width':1200,'height':1800,'profile':['http://iiif.io/api/image/2/level1.json']}]
    api.cached_bytes.return_value=ALTO
    result=LOCProvider(api).search('submarine 1968',['document'],1)[0]
    assert result.provider=='loc' and '/full/1200,/' in result.download_url
    assert result.metadata['loc_services']['text']['text']=='Soviet submarine'
    assert result.metadata['loc_services']['images']['status']=='available'
    assert 'OCR (source data)' in result.description
    assert api.json.call_args_list[0].args[0]=='loc_json'
    api.cached_bytes.assert_called_once()


def test_uncertain_rights_never_fetch_pixels_or_ocr():
    api=Mock();api.settings=ArchiveSettings()
    api.json.side_effect=[{'results':[{'id':'https://www.loc.gov/item/123/'}]},
        {'item':{'title':'Document','original_format':['manuscript'],'image_url':[BASE+'/full/full/0/default.jpg']},
         'resources':[{'files':[[{'url':'https://tile.loc.gov/files/page.alto.xml'}]]}]}]
    candidate=LOCProvider(api).search('document',['document'],1)[0]
    assert candidate.metadata['loc_services']['text']['status']=='skipped_uncertain_rights'
    assert api.json.call_count==2
    api.cached_bytes.assert_not_called()


def test_loc_off_does_not_reserve_quota_or_fetch_cached_ocr(tmp_path):
    transport=Transport(tmp_path,ArchiveSettings(),lambda:False)
    with patch.object(network.requests,'get') as http:
        with pytest.raises(ArchiveDisabled):transport.get('loc_json','https://www.loc.gov/search/')
        with pytest.raises(ArchiveDisabled):transport.cached_bytes('loc_text',TEXT)
        http.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_iiif_respects_server_maximum_dimensions():
    api=Mock();api.settings=ArchiveSettings()
    api.json.return_value={'@id':BASE,'width':4000,'height':2000,'maxWidth':1024,
                           'profile':['http://iiif.io/api/image/2/level2.json']}
    result=LOCImageService(api).prepare({'url':BASE+'/info.json'})
    assert result['image_url']==BASE+'/full/1024,/0/default.jpg'
    assert result['output_width']==1024 and result['output_height']==512


@pytest.mark.parametrize('field,cap',[('loc_json_rpm',20),('loc_image_rpm',150),('loc_text_rpm',150)])
def test_config_cannot_raise_official_service_caps(field,cap):
    with pytest.raises(ValueError):ArchiveSettings(**{field:cap+1})
    assert getattr(ArchiveSettings(**{field:1}),field)==1


def test_loc_configuration_never_introduces_api_key_fields():
    assert not any(name.startswith('loc_') and any(secret in name for secret in ('key','token','password','auth')) for name in ArchiveSettings.model_fields)


def test_concurrent_service_block_cannot_shorten_existing_wait(tmp_path,monkeypatch):
    transport=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:True)
    fake_clock(monkeypatch,transport)
    transport._record_cooldown('loc_json',response(429,headers={'Retry-After':'3600'}))
    transport._record_cooldown('loc_image',response(429,headers={'Retry-After':'60'}))
    assert json.loads((tmp_path/'loc-cooldown.json').read_text())['until']==4600


def test_iiif_accepts_equivalent_encoded_identifier_but_not_another_image():
    api=Mock();api.settings=ArchiveSettings()
    api.json.return_value={'@id':BASE.replace('service:','service%3A'),'width':1000,'height':800,
                           'profile':'http://iiif.io/api/image/2/level2.json'}
    assert LOCImageService(api).prepare({'url':BASE+'/info.json'})['status']=='available'
    api.json.return_value['@id']=BASE+'-different'
    with pytest.raises(ArchiveError,match='outro identificador'):LOCImageService(api).prepare({'url':BASE+'/info.json'})
