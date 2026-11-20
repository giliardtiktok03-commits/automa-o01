import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import pytest
from PIL import Image
from app.models.historical_director import Request,VideoProduction,PublicationOptions
from app.services.autopilot.recovery import RecoveryBlocked
from app.services.historical_director import publication as bridge
from app.services.youtube_publish import service as yt
from app.services.youtube_publish.store import digest,put
from test.services.test_youtube_direct import setup,CHANNEL,GOOGLE,execute,response,VIDEO,SESSION


def bundle(env,mode='prepare'):
    store,video,thumb,*_=env;task=video.parent.name
    original=store.root/'thumbnails'/thumb
    out=video.parent/'youtube-thumbnail.jpg'
    with Image.open(original) as im:im.convert('RGB').save(out,format='JPEG')
    cfg=store.connection(CHANNEL);cfg['skill_auto_upload']=True;store.save_connection(CHANNEL,cfg)
    request=Request(title='Historical title',production=VideoProduction(mode='video',generate_thumbnail=True),
        publication=PublicationOptions(mode=mode,youtube_channel_id=GOOGLE,contains_synthetic_media=True))
    result={'job_id':task,'batch_id':'batch-example','angle_id':'angle_01','title':'Historical title',
        'script':'Independently researched narration.','research':{'claims':[]},'quality_report':{'approved':True},
        'metadata':{'description':'Editorial description with reliable references.','tags':['history'],'hashtags':['#History']},
        'media':{'video':{'file':video.name,'sha256':digest(video),'bytes':video.stat().st_size,'decode_verified':True}},
        'thumbnail_image':{'file':out.name,'sha256':digest(out),'bytes':out.stat().st_size}}
    snapshot=SimpleNamespace(channel=SimpleNamespace(channel_id=CHANNEL,language='en'))
    return request,result,snapshot


def test_packet_has_per_angle_metadata_and_disclosures_no_manual_channel_copy(setup):
    store,video,*_=setup;request,result,snapshot=bundle(setup)
    cfg=store.connection(CHANNEL);cfg.update(description='Wrong manual description',tags=['WRONG']);store.save_connection(CHANNEL,cfg)
    packet=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    posted=bridge.prepare(video.parent.name,packet,request,store)
    job=store.job(posted['job_id'])
    assert job['metadata']['snippet']['description']=='Editorial description with reliable references.\n\n#History'
    assert job['metadata']['snippet']['tags']==['history']
    assert job['metadata']['status']['selfDeclaredMadeForKids'] is False
    assert job['metadata']['status']['containsSyntheticMedia'] is True
    assert job['origin']=='director_package' and job['angle_id']=='angle_01'
    assert job['source_package']['sha256']==packet['sha256']
    assert len(store.jobs(CHANNEL))==1
    assert bridge.prepare(video.parent.name,packet,request,store)['job_id']==job['id']


@pytest.mark.parametrize('what',['video','thumbnail','packet','channel','job_id'])
def test_refuses_mixed_or_changed_assets(setup,what):
    store,video,thumb,*_=setup;request,result,snapshot=bundle(setup)
    if what=='job_id':
        result['job_id']='other-angle'
        with pytest.raises(RecoveryBlocked):bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
        return
    packet=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    if what=='video':video.write_bytes(b'changed')
    if what=='thumbnail':(video.parent/'youtube-thumbnail.jpg').write_bytes(b'changed')
    if what=='packet':(video.parent/'youtube-package.json').write_text('{}')
    if what=='channel':store.save_connection(CHANNEL,{'connected':True,'youtube_channel_id':'UC'+'z'*22})
    with pytest.raises(RecoveryBlocked):bridge.prepare(video.parent.name,packet,request,store)


def test_distinct_angles_do_not_share_metadata(setup):
    store,video,*_=setup;request,result,snapshot=bundle(setup)
    first=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    one=bridge.prepare(video.parent.name,first,request,store)
    from copy import deepcopy
    new=video.parent.parent/'b510f09c-98fd-4315-aa45-c090e331a34c';new.mkdir()
    newvideo=new/'final-1.mp4';newvideo.write_bytes(b'different angle video')
    (new/'youtube-thumbnail.jpg').write_bytes((video.parent/'youtube-thumbnail.jpg').read_bytes())
    other=deepcopy(result);other.update(job_id=new.name,angle_id='angle_02',title='Different historical angle')
    other['metadata']['description']='A distinct description and its own historical references.'
    other['media']['video'].update(sha256=digest(newvideo),bytes=newvideo.stat().st_size)
    second=bridge.make_package(new.name,snapshot,other,request,other['title'])
    two=bridge.prepare(new.name,second,request,store)
    assert one['job_id']!=two['job_id']
    assert store.job(two['job_id'])['metadata']['snippet']['title']==other['title']
    assert store.job(one['job_id'])['metadata']['snippet']['title']==result['title']


def test_skill_auto_consent_separate_from_manual_generation(setup):
    store,video,*_=setup;request,result,snapshot=bundle(setup,'automatic')
    cfg=store.connection(CHANNEL);cfg['auto_upload']=False;store.save_connection(CHANNEL,cfg)
    packet=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    posted=bridge.prepare(video.parent.name,packet,request,store)
    api=setup[3];api.post.side_effect=[response(headers={'Location':SESSION}),response()]
    api.put.side_effect=[response(308),response(data={'id':VIDEO})]
    assert execute(setup,posted['job_id'])['state']=='completed'
    assert api.post.call_args_list[0].kwargs['json']['status']['containsSyntheticMedia'] is True
    assert api.post.call_args_list[0].kwargs['json']['status']['selfDeclaredMadeForKids'] is False


def test_changed_packet_blocks_network_even_after_prepare(setup):
    store,video,*_=setup;request,result,snapshot=bundle(setup)
    packet=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    posted=bridge.prepare(video.parent.name,packet,request,store)
    (video.parent/'youtube-package.json').write_text('{}')
    with pytest.raises(Exception,match='pacote editorial'):execute(setup,posted['job_id'])
    setup[4].assert_not_called()


def test_no_new_actions_for_old_requests():
    request=Request(title='Old project')
    assert not request.production.generate_thumbnail
    assert request.publication.mode=='off'
    assert request.publish_mode=='off'


def test_thumbnail_reuses_deepinfra_api_and_does_not_change_global_settings(setup):
    from app.services import deepinfra_image
    store,video,thumb,*_=setup;request,result,snapshot=bundle(setup)
    result['thumbnail_concepts']={'concepts':[{'prompt_en':'Historical archival aircraft scene, 16:9','negative_prompt':'No modern planes'}]*3}
    def render(prompt,directory,**kwargs):
        image=Path(directory)/'thumbnail.png';Image.new('RGB',(1280,720),'navy').save(image)
        assert kwargs['settings']['deepinfra_thumbnails_enabled'] is True
        assert kwargs['model_id']=='PrunaAI/p-image'
        return image,{'model':'PrunaAI/p-image'}
    settings={'deepinfra_api_key':'TEST_ONLY','deepinfra_thumbnails_enabled':False}
    with patch.object(bridge.ed,'settings_for',return_value=settings),patch.object(deepinfra_image,'generate_thumbnail',side_effect=render) as generate:
        record=bridge.thumbnail(video.parent.name,snapshot,result,request.production)
    assert settings['deepinfra_thumbnails_enabled'] is False
    assert record['width']==1280 and record['height']==720
    assert bridge.verify_thumbnail(video.parent.name,record).name=='youtube-thumbnail.jpg'
    generate.assert_called_once()


def test_long_title_uses_reviewed_short_title_without_changing_script(setup):
    request,result,snapshot=bundle(setup);result['title']='Historical title '*10
    original=result['title'];result['script']='Original approved script'
    with patch.object(bridge.ed,'text',return_value=SimpleNamespace(title='A faithful short historical title')),patch.object(bridge.ed,'approved_review',return_value={'approved':True}) as review:
        shorter=bridge.youtube_title(snapshot,result)
    assert shorter['shortened'] and len(shorter['title'])<=100
    assert result['title']==original and result['script']=='Original approved script'
    review.assert_called_once()


def test_disclosure_false_is_explicit_and_child_flag_independent():
    data=yt.metadata('Title','Description',['history'],'private',False,False)
    assert data['status']['containsSyntheticMedia'] is False
    assert data['status']['selfDeclaredMadeForKids'] is False


def test_hashtags_preserve_managed_commons_credit_block_at_end(setup):
    store,video,*_=setup;request,result,snapshot=bundle(setup)
    block='Historical Image Credits\n\nVerified historical image and its source.'
    result['metadata']['description']='SEO description. Historical references remain here.\n\n'+block
    put(video.parent/'historical_archive'/'commons-description-block.json',{'final-1.mp4':block})
    packet=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    description=packet['packet']['metadata']['snippet']['description']
    assert description.endswith('\n\n'+block)
    assert description.index('#History')<description.index('Historical Image Credits')
    assert description.startswith('SEO description. Historical references remain here.')


def test_commons_package_becomes_manual_review_instead_of_auto_upload(setup):
    from app.services.historical_archive import commons_credits as credits
    store,video,*_=setup;request,result,snapshot=bundle(setup,'automatic')
    packet=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    with patch.object(credits,'locate',return_value=video.parent/'historical_archive'),patch.object(credits,'has_commons',return_value=True),patch.object(credits,'prepare_description',side_effect=lambda video,description:description):
        posted=bridge.prepare(video.parent.name,packet,request,store)
    job=store.job(posted['job_id'])
    assert posted['mode']=='manual_review' and not job['automatic'] and job['review_required']
    with pytest.raises(Exception,match='confirme a revisão'):execute(setup,job['id'])
    setup[4].assert_not_called()


def test_review_required_package_has_disabled_upload_until_explicit_confirmation(setup):
    from streamlit.testing.v1 import AppTest
    store,video,*_=setup;request,result,snapshot=bundle(setup)
    packet=bridge.make_package(video.parent.name,snapshot,result,request,result['title'])
    posted=bridge.prepare(video.parent.name,packet,request,store)
    with patch.object(yt,'submit') as submit:
        app=AppTest.from_string("from webui.youtube_publish import history\nhistory('"+CHANNEL+"')").run()
        assert not app.exception
        assert app.button(key='yt_resume_'+posted['job_id']).disabled
        app.checkbox(key='yt_review_'+posted['job_id']).check().run()
        app.button(key='yt_resume_'+posted['job_id']).click().run()
        assert not app.exception
        assert submit.call_args.kwargs['reviewed'] is True
