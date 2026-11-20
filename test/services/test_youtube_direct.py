import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
import requests
from PIL import Image
from app.models.schema import VideoParams
from app.services.youtube_publish import service as yt,auth
from app.services.youtube_publish.store import Store,PublishError,digest,put

CHANNEL='beyond-the-archives'
GOOGLE='UC'+'a'*22
OTHER='UC'+'b'*22
VIDEO='abcdefghijk'
SESSION=yt.UPLOAD+'?uploadType=resumable&upload_id=PRIVATE_SESSION_TOKEN'


def response(code=200,data=None,headers=None):
    return SimpleNamespace(status_code=code,json=lambda:data or {},headers=headers or {})


@pytest.fixture
def setup(tmp_path,monkeypatch):
    from app.utils import utils
    root=tmp_path/'tasks';folder=root/'ef171cc2-40b8-4cd3-a351-14803c095f3e';folder.mkdir(parents=True)
    monkeypatch.setattr(utils,'task_dir',lambda *a,**kw:str(root))
    monkeypatch.setattr(utils,'storage_dir',lambda name='',create=False:str(tmp_path/name))
    store=Store();store.save_connection(CHANNEL,{'connected':True,'youtube_channel_id':GOOGLE,'youtube_channel_name':'Beyond','auto_upload':True})
    video=folder/'final-1.mp4';video.write_bytes(b'fake video bytes only for mocked verifier')
    image=io.BytesIO();Image.new('RGB',(1280,720),'navy').save(image,format='PNG')
    thumb=yt.save_thumbnail(image.getvalue(),store)
    api=Mock();api.__enter__=Mock(return_value=api);api.__exit__=Mock(return_value=None)
    api.get.return_value=response(data={'items':[{'id':GOOGLE,'snippet':{'title':'Beyond'}}]})
    factory=Mock(return_value=api)
    verifier=Mock(return_value={'decode_verified':True,'sha256':digest(video),'duration':60})
    return store,video,thumb,api,factory,verifier


def prepare(env,**kw):
    store,video,thumb,*_=env
    return yt.prepare(CHANNEL,video,'Historical title','Description with references',['history','world war'],thumb,store=store,**kw)


def execute(env,key):
    store,_,_,_,factory,verifier=env
    return yt.execute(key,store,factory,verifier)


def uploads(api):return [c for c in api.post.call_args_list if c.args[0]==yt.UPLOAD]


def test_upload_metadata_thumbnail_and_persistent_dedup(setup):
    store,video,thumb,api,factory,verifier=setup
    job=prepare(setup)
    api.post.side_effect=[response(headers={'Location':SESSION}),response()]
    api.put.side_effect=[response(308),response(data={'id':VIDEO})]
    result=execute(setup,job['id'])
    assert result['state']=='completed' and result['url'].endswith(VIDEO)
    assert uploads(api)[0].kwargs['json']['snippet']['tags']==['history','world war']
    assert uploads(api)[0].kwargs['json']['status']['privacyStatus']=='private'
    assert api.post.call_args.kwargs['params']['videoId']==VIDEO
    assert api.put.call_args_list[-1].kwargs['headers']['Content-Range']==f'bytes 0-{video.stat().st_size-1}/{video.stat().st_size}'
    assert all(c.kwargs['allow_redirects'] is False for c in api.post.call_args_list+api.put.call_args_list)
    api.reset_mock()
    assert prepare(setup)['id']==job['id']
    assert execute(setup,job['id'])['state']=='completed'
    api.post.assert_not_called();api.get.assert_not_called()
    assert 'PRIVATE_SESSION_TOKEN' not in json.dumps(store.job(job['id']))


def test_network_loss_resumes_without_second_insert(setup):
    store,video,thumb,api,*_=setup
    job=prepare(setup)
    api.post.return_value=response(headers={'Location':SESSION})
    api.put.side_effect=[response(308),requests.ConnectionError('private secret-token')]
    with pytest.raises(PublishError):execute(setup,job['id'])
    assert 'secret-token' not in json.dumps(store.job(job['id']))
    api.post.reset_mock();api.post.side_effect=None;api.post.return_value=response()
    api.put.side_effect=[response(308,headers={'Range':'bytes=0-4'}),response(data={'id':VIDEO})]
    assert execute(setup,job['id'])['state']=='completed'
    assert not uploads(api)
    assert api.put.call_args.kwargs['headers']['Content-Range'].startswith('bytes 5-')


def test_lost_final_response_recovers_server_video_id(setup):
    store,_,_,api,*_=setup;job=prepare(setup)
    api.post.return_value=response(headers={'Location':SESSION})
    api.put.side_effect=[response(308),requests.Timeout('secret')]
    with pytest.raises(PublishError):execute(setup,job['id'])
    api.post.reset_mock();api.post.return_value=response()
    api.put.side_effect=[response(data={'id':VIDEO})]
    assert execute(setup,job['id'])['state']=='completed'
    assert not uploads(api) and api.put.call_count==3


def test_thumbnail_retry_never_reuploads(setup):
    store,_,_,api,*_=setup;job=prepare(setup)
    api.post.side_effect=[response(headers={'Location':SESSION}),response(403,{'error':{'errors':[{'reason':'forbidden'}]}})]
    api.put.side_effect=[response(308),response(data={'id':VIDEO})]
    with pytest.raises(PublishError):execute(setup,job['id'])
    assert store.job(job['id'])['video_id']==VIDEO
    api.post.reset_mock();api.put.reset_mock();api.post.side_effect=None;api.post.return_value=response()
    assert execute(setup,job['id'])['state']=='completed'
    assert not uploads(api);api.put.assert_not_called()


def test_ambiguous_initiation_blocks_new_upload(setup):
    store,_,_,api,*_=setup;job=prepare(setup)
    api.post.side_effect=requests.Timeout('private')
    with pytest.raises(PublishError):execute(setup,job['id'])
    api.reset_mock()
    with pytest.raises(PublishError,match='sem confirmação'):execute(setup,job['id'])
    api.post.assert_not_called();api.get.assert_not_called()


def test_quota_stops_and_safe_retry_does_not_duplicate(setup,monkeypatch):
    store,_,_,api,*_=setup;job=prepare(setup)
    api.post.return_value=response(403,{'error':{'errors':[{'reason':'quotaExceeded','message':'secret'}]}})
    with pytest.raises(PublishError):execute(setup,job['id'])
    assert store.job(job['id'])['state']=='quota_wait'
    api.reset_mock()
    with pytest.raises(PublishError,match='Aguarde'):execute(setup,job['id'])
    api.post.assert_not_called()
    job=store.job(job['id']);job['retry_after']=0;store.save_job(job)
    api.post.side_effect=[response(headers={'Location':SESSION}),response()]
    api.put.side_effect=[response(308),response(data={'id':VIDEO})]
    assert execute(setup,job['id'])['state']=='completed'


@pytest.mark.parametrize('change',['video','thumbnail','channel','qa'])
def test_preflight_failures_never_upload(setup,change):
    store,video,thumb,api,factory,verifier=setup;job=prepare(setup)
    if change=='video':video.write_bytes(b'changed')
    if change=='thumbnail':(store.root/'thumbnails'/thumb).write_bytes(b'changed')
    if change=='channel':store.save_connection(CHANNEL,{'connected':True,'youtube_channel_id':OTHER})
    if change=='qa':verifier.return_value={'decode_verified':False}
    with pytest.raises(PublishError):execute(setup,job['id'])
    factory.assert_not_called();api.post.assert_not_called()


def test_wrong_google_identity_never_sends_video(setup):
    store,_,_,api,*_=setup;job=prepare(setup)
    api.get.return_value=response(data={'items':[{'id':OTHER}]})
    with pytest.raises(PublishError,match='diferente'):execute(setup,job['id'])
    api.post.assert_not_called()


def test_commons_blocks_automatic_and_reconciles_manual(setup):
    from app.services.historical_archive import commons_credits as credits
    with patch.object(credits,'locate',return_value=Path('/unused')),patch.object(credits,'has_commons',return_value=True),patch.object(credits,'prepare_description',return_value='Description\n\nHistorical Image Credits') as reconcile:
        with pytest.raises(PublishError,match='revisão'):prepare(setup,automatic=True)
        assert prepare(setup)['metadata']['snippet']['description'].endswith('Historical Image Credits')
        reconcile.assert_called_once()


@pytest.mark.parametrize('url',['http://www.googleapis.com/upload/youtube/v3/videos','https://evil.example/upload/youtube/v3/videos','https://www.googleapis.com/other','https://user:secret@www.googleapis.com/upload/youtube/v3/videos'])
def test_session_url_only_official(url):
    with pytest.raises(PublishError):yt.safe_session_url(url)


@pytest.mark.parametrize('kwargs',[{'title':'x'*101},{'description':''},{'tags':['a'*501]},{'made_for_kids':'false'},{'privacy':'unknown'}])
def test_metadata_limits(kwargs):
    data={'title':'Title','description':'Description','tags':['history'],'privacy':'private','made_for_kids':False};data.update(kwargs)
    with pytest.raises(PublishError):yt.metadata(**data)


def test_oauth_rejects_web_client_or_foreign_endpoints():
    for value in [{'web':{}},{'installed':{'client_id':'x','client_secret':'x','auth_uri':'https://evil.example','token_uri':'https://oauth2.googleapis.com/token'}}]:
        with pytest.raises(PublishError):auth.client_config(json.dumps(value).encode())


def test_existing_projects_default_to_no_upload():
    assert VideoParams(video_subject='Title').youtube_publication=={}
    with patch.object(yt,'submit') as submit:
        assert yt.after_generation(VideoParams(video_subject='Title'),[]) is None
        submit.assert_not_called()


def test_posting_disabled_after_task_creation(setup):
    store,_,_,api,*_=setup;job=prepare(setup,automatic=True)
    cfg=store.connection(CHANNEL);cfg['auto_upload']=False;store.save_connection(CHANNEL,cfg)
    with pytest.raises(PublishError,match='desativado'):execute(setup,job['id'])
    api.post.assert_not_called()


def test_auto_queue_uses_saved_channel_and_metadata(setup,monkeypatch):
    store,video,thumb,_,*_=setup
    params=VideoParams(video_subject='New title',youtube_publication={'channel_id':CHANNEL,'youtube_channel_id':GOOGLE,
        'description':'Editorial description with references','tags':['history'],'thumbnail':thumb,'privacy':'private','made_for_kids':False,'auto_upload':True})
    from app.config import config
    monkeypatch.setitem(config.app,'upload_post_auto_upload',False)
    with patch.object(yt,'submit') as submit:
        result=yt.after_generation(params,[str(video)])
        assert result['state']=='prepared'
        job=store.job(result['job_id']);assert job['metadata']['snippet']['title']=='New title'
        submit.assert_called_once()


def test_ui_has_numbered_module_and_does_not_network_on_rerun(setup,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app.services.autopilot.repository import Repository
    monkeypatch.setattr(Repository,'channels',lambda self:[{'channel_id':CHANNEL,'name':'Beyond'}])
    with patch.object(auth,'connect') as connect,patch.object(yt,'submit') as submit,patch('requests.sessions.Session.request',side_effect=AssertionError('network on render')):
        app=AppTest.from_string("from webui.youtube_publish import render\nfrom app.models.schema import VideoParams\nrender(VideoParams(video_subject='Test'))").run()
        assert not app.exception
        assert app.button(key='yt_prepare').disabled
        assert any('Postagem automática youtube' in str(s.value) for s in app.subheader)
        connect.assert_not_called();submit.assert_not_called()


def test_public_visibility_only_after_thumbnail_and_retry_no_upload(setup):
    store,_,_,api,*_=setup;job=prepare(setup,privacy='public')
    api.post.side_effect=[response(headers={'Location':SESSION}),response(403)]
    api.put.side_effect=[response(308),response(data={'id':VIDEO})]
    with pytest.raises(PublishError):execute(setup,job['id'])
    assert uploads(api)[0].kwargs['json']['status']['privacyStatus']=='private'
    assert not any(c.args[0]==auth.API+'/videos' for c in api.put.call_args_list)
    api.reset_mock();api.post.side_effect=None;api.post.return_value=response()
    api.put.side_effect=[response(data={'status':{'privacyStatus':'public'}})]
    assert execute(setup,job['id'])['state']=='completed'
    assert not uploads(api)
    assert api.put.call_args.args[0]==auth.API+'/videos'


def test_oauth_desktop_loopback_and_saved_credentials_never_enter_reports(setup,monkeypatch):
    import threading,time
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import AuthorizedSession
    store,_,_,api,*_=setup
    # Simulate OAuth only; no Google request is made by this test.
    config={'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'PRIVATE_SECRET',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token'}}
    credentials=SimpleNamespace(refresh_token='PRIVATE_REFRESH',to_json=lambda:json.dumps({'token':'PRIVATE_TOKEN','refresh_token':'PRIVATE_REFRESH','token_uri':config['installed']['token_uri']}))
    flow=Mock();flow.authorization_url.return_value=('https://accounts.google.com/o/oauth2/auth?state=STATE','STATE')
    def run(**kwargs):
        assert kwargs['host']=='127.0.0.1' and kwargs['port']==0 and kwargs['open_browser'] is False
        assert kwargs['authorization_prompt_message'] is None
        assert kwargs['access_type']=='offline'
        flow.authorization_url(access_type='offline',prompt='consent')
        return credentials
    flow.run_local_server.side_effect=run
    with patch.object(InstalledAppFlow,'from_client_config',return_value=flow) as build,patch('google.auth.transport.requests.AuthorizedSession',return_value=api):
        auth.connect(CHANNEL,json.dumps(config).encode(),store)
        deadline=time.monotonic()+3
        while auth.status(CHANNEL).get('state') in {'starting','waiting'} and time.monotonic()<deadline:time.sleep(.01)
        assert auth.status(CHANNEL)['state']=='connected'
        assert build.call_args.kwargs['autogenerate_code_verifier'] is True
    assert 'PRIVATE' not in json.dumps(store.connection(CHANNEL))
    assert 'PRIVATE' not in json.dumps(auth.status(CHANNEL))
    assert json.loads(store.secret_path(CHANNEL).read_text())['refresh_token']=='PRIVATE_REFRESH'
    auth.disconnect(CHANNEL,store)
    assert not store.secret_path(CHANNEL).exists()
    assert not store.connection(CHANNEL)['auto_upload']


def test_file_changed_during_upload_never_gets_thumbnail_or_public_visibility(setup):
    store,video,_,api,*_=setup;job=prepare(setup,privacy='public')
    api.post.return_value=response(headers={'Location':SESSION})
    calls=[0]
    def put_response(*args,**kwargs):
        calls[0]+=1
        if calls[0]==1:return response(308)
        video.write_bytes(b'changed while uploading')
        return response(data={'id':VIDEO})
    api.put.side_effect=put_response
    with pytest.raises(PublishError,match='durante o envio'):execute(setup,job['id'])
    assert len(api.post.call_args_list)==1
    assert all(c.args[0]!=auth.API+'/videos' for c in api.put.call_args_list)
    assert store.job(job['id'])['video_id']==VIDEO


def test_google_retry_after_is_not_shortened(setup):
    import time
    store,_,_,api,*_=setup;job=prepare(setup)
    api.post.return_value=response(429,headers={'Retry-After':'3600'})
    before=time.time()
    with pytest.raises(PublishError):execute(setup,job['id'])
    assert store.job(job['id'])['retry_after']>=before+3600
