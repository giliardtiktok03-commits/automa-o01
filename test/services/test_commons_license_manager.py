"""Conservative Commons policy, full audit, exact render bindings and upload gates."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from app.models.schema import VideoParams
from app.services.historical_archive.contracts import ArchiveCandidate,ArchiveError
from app.services.historical_archive.providers.wikimedia import WikimediaProvider
from app.services.historical_archive.commons_license import classify
from app.services.historical_archive import commons_credits as credits, manifest
from app.services.historical_archive.service import HistoricalArchiveService
from test.services.test_wikimedia_commons import record


def commons(kind='pd',**changes):
    raw=record()
    ext=raw['query']['pages']['2110142']['imageinfo'][0]['extmetadata']
    if kind=='by':ext.update(LicenseShortName={'value':'CC BY 4.0'},UsageTerms={'value':'Creative Commons Attribution 4.0'},
        Copyrighted={'value':'True'},AttributionRequired={'value':'true'},LicenseUrl={'value':'https://creativecommons.org/licenses/by/4.0/'})
    if kind=='cc0':ext.update(LicenseShortName={'value':'CC0 1.0'},UsageTerms={'value':'CC0'},
        LicenseUrl={'value':'https://creativecommons.org/publicdomain/zero/1.0/'})
    if kind=='sa':ext.update(LicenseShortName={'value':'CC BY-SA 4.0'},UsageTerms={'value':'Creative Commons Attribution-Share Alike'},
        LicenseUrl={'value':'https://creativecommons.org/licenses/by-sa/4.0/'},Copyrighted={'value':'True'})
    for name,value in changes.items():ext[name]={'value':value}
    ext['Artist']={'value':'Named photographer'};ext['Credit']={'value':'Museum collection, record 123'}
    transport=Mock();transport.json.return_value=raw
    return WikimediaProvider(transport).search('aircraft 1943',['photograph'],1)[0]


@pytest.mark.parametrize('kind',['pd','cc0','by'])
def test_explicit_consistent_licenses_approved_with_traceable_fields(kind):
    decision=classify(commons(kind))
    assert decision['classification']=='AUTO_APPROVED'
    assert decision['checked_at'] and decision['original_metadata']
    assert decision['attribution_required']==(kind=='by')


@pytest.mark.parametrize('changes',[
    {'Copyrighted':'True'}, {'Copyrighted':''}, {'License':''},
    {'Restrictions':'Personality rights'}, {'UsageTerms':'Public domain in the US only'},
    {'LicenseShortName':''}, {'AttributionRequired':'true'},
    {'LicenseUrl':'https://creativecommons.org/licenses/by/4.0/'}])
def test_incomplete_or_conflicting_public_domain_is_review_not_availability_approval(changes):
    assert classify(commons(**changes))['classification']=='NEEDS_REVIEW'


@pytest.mark.parametrize('name',['CC BY-NC 4.0','CC BY-ND 4.0','All rights reserved'])
def test_incompatible_licenses_rejected(name):
    assert classify(commons(LicenseShortName=name))['classification']=='REJECTED'


def test_by_sa_and_missing_or_contradictory_attribution_are_held():
    assert classify(commons('sa'))['classification']=='NEEDS_REVIEW'
    assert classify(commons('by',AttributionRequired='false'))['classification']=='NEEDS_REVIEW'
    assert classify(commons('by',LicenseShortName='CC BY 3.0'))['classification']=='NEEDS_REVIEW'
    c=commons('by');c.creator='Unknown author'
    assert classify(c)['classification']=='NEEDS_REVIEW'


def test_other_providers_retain_existing_rights_behavior():
    from app.services.historical_archive.rights import assess
    c=commons('sa');c.provider='loc'
    assert assess(c)[0]=='rights_cleared'
    c.provider='nara'
    assert assess(c)[0]=='rights_cleared'


@pytest.fixture
def project(tmp_path,monkeypatch):
    from app.utils import utils
    monkeypatch.setattr(utils,'storage_dir',lambda:str(tmp_path))
    root=tmp_path/'tasks'/'license-test';folder=root/'historical_archive';folder.mkdir(parents=True)
    source=folder/'original.png';source.write_bytes(b'validated historical image')
    scene=root/'scene.mp4';scene.write_bytes(b'validated rendered scene')
    video=root/'final-1.mp4';video.write_bytes(b'validated final video')
    c=commons('by')
    params=VideoParams(video_subject='History',video_aspect='16:9',video_fit_mode='contain')
    item={'id':'image1','candidate':c.to_dict(),'used':True,'rights_status':'rights_cleared',
        'downloaded_file':'original.png','sha256':credits.digest(source),'commons_license':classify(c)}
    item['commons_render_use']=credits.record_use(folder,item,scene,params)
    data={'version':1,'providers':{'wikimedia':{'status':'available'}},'downloads':{},
        'scenes':{'scene_001':{'candidates':[item],'searched_at':manifest.now()}}}
    manifest.save(folder,data)
    credits.bind_final('license-test',video,[scene])
    return folder,video,scene,source,data


def test_credits_preserve_seo_sources_and_are_idempotent(project):
    folder,video,*_=project
    description='Original SEO description.\n\nHistorical sources\nhttps://archive.example/record'
    result=credits.prepare_description(video,description)
    assert result.startswith(description+'\n\nHistorical Image Credits')
    assert 'Named photographer' in result and 'https://creativecommons.org/licenses/by/4.0/' in result
    assert 'Changes:' in result and 'Padding preserves original aspect ratio' in result
    assert credits.prepare_description(video,result)==result
    review=json.loads((folder/'commons-publication-review.json').read_text())
    assert review['status']=='ready_for_manual_publication' and not review['automatic_publication']


def test_description_limit_never_truncates_original_or_credits(project):
    folder,video,*_=project
    with pytest.raises(ArchiveError,match='excedem'):credits.prepare_description(video,'SEO '*1240)
    assert json.loads((folder/'commons-publication-review.json').read_text())['status']=='NEEDS_REVIEW'


@pytest.mark.parametrize('which',['video','scene','source','missing_proof','missing_credit','extra_image'])
def test_final_reconciliation_blocks_divergent_files_metadata_and_image_list(project,which):
    folder,video,scene,source,data=project
    if which in {'video','scene','source'}:{'video':video,'scene':scene,'source':source}[which].write_bytes(b'changed')
    elif which=='missing_proof':(folder/'commons-final-media.json').unlink()
    elif which=='missing_credit':
        item=data['scenes']['scene_001']['candidates'][0]
        item['candidate']['creator']='';manifest.save(folder,data)
    else:
        extra=deepcopy(data['scenes']['scene_001']['candidates'][0]);extra['id']='uncredited-image'
        data['scenes']['scene_001']['candidates'].append(extra);manifest.save(folder,data)
    with pytest.raises(ArchiveError):credits.prepare_description(video,'SEO')
    assert json.loads((folder/'commons-publication-review.json').read_text())['status']=='NEEDS_REVIEW'


def test_audit_retains_rejected_candidate_outside_shortlist(tmp_path,monkeypatch):
    from app.utils import utils
    monkeypatch.setattr(utils,'storage_dir',lambda:str(tmp_path))
    approved=commons();rejected=commons(LicenseShortName='CC BY-NC 4.0');rejected.record_id='rejected';rejected.download_url='https://upload.wikimedia.org/different.jpg'
    provider=Mock(name='provider');provider.name='wikimedia';provider.search.return_value=[approved,rejected]
    values={'historical_archive_enabled':True,'historical_archive_candidates_per_scene':1,'historical_archive_min_score':0}
    service=HistoricalArchiveService('audit-test',settings_getter=lambda:values,provider_factory=lambda *a:[provider])
    entry=service.search_scene({'id':1,'text':'aircraft 1943','search_query':'aircraft 1943'})
    assert len(entry['candidates'])==1
    audit=json.loads((service.folder/'commons-license-audit.json').read_text())
    assert len(audit['files'])==2 and {f['classification'] for f in audit['files']}=={'AUTO_APPROVED','REJECTED'}


def test_upload_blocks_before_any_external_request_when_credits_pending(project,monkeypatch):
    from app.services import upload_post
    folder,video,*_=project
    (folder/'commons-final-media.json').unlink()
    service=upload_post.UploadPostService()
    monkeypatch.setattr(service,'is_configured',lambda:True)
    post=Mock();monkeypatch.setattr(upload_post.requests,'post',post)
    result=service.upload_video(str(video),'SEO',platforms=['youtube'],youtube_extra={'selfDeclaredMadeForKids':False,'youtube_description':'SEO'})
    assert not result['success'] and result['needs_review']
    post.assert_not_called()


def test_used_flag_cannot_bypass_final_video_credit_binding(project):
    folder,video,_,_,data=project
    data['scenes']['scene_001']['candidates'][0]['used']=False
    manifest.save(folder,data)
    with pytest.raises(ArchiveError):credits.prepare_description(video,'SEO')


def test_audit_and_selection_hold_conflicting_records_for_same_file(tmp_path,monkeypatch):
    from app.utils import utils
    monkeypatch.setattr(utils,'storage_dir',lambda:str(tmp_path))
    approved=commons();restricted=commons(LicenseShortName='CC BY-NC 4.0');restricted.record_id='contradictory'
    provider=Mock();provider.name='wikimedia';provider.search.return_value=[approved,restricted]
    service=HistoricalArchiveService('duplicate-test',settings_getter=lambda:{'historical_archive_enabled':True},provider_factory=lambda *a:[provider])
    entry=service.search_scene({'id':1,'text':'aircraft 1943'})
    assert all(i['rights_status']!='rights_cleared' for i in entry['candidates'])
    assert len(json.loads((service.folder/'commons-license-audit.json').read_text())['files'])==2


def test_manual_youtube_payload_receives_complete_credits_without_changing_seo(project,monkeypatch):
    from app.services import upload_post
    from test.services.test_upload_post import _mock_response,_get
    folder,video,*_=project
    service=upload_post.UploadPostService()
    monkeypatch.setattr(service,'is_configured',lambda:True)
    post=Mock(return_value=_mock_response());monkeypatch.setattr(upload_post.requests,'post',post)
    supplied={'selfDeclaredMadeForKids':False,'youtube_description':'SEO and research references retained.'}
    result=service.upload_video(str(video),'Title',platforms=['youtube'],youtube_extra=supplied)
    assert result['success'] and post.call_count==1
    description=_get(post.call_args.kwargs['data'],'youtube_description')
    assert description.startswith(supplied['youtube_description']) and 'Historical Image Credits' in description
    assert supplied=={'selfDeclaredMadeForKids':False,'youtube_description':'SEO and research references retained.'}


def test_commons_final_is_not_automatically_queued_for_publication(project,monkeypatch):
    from app.services import task
    from app.services.state import MemoryState
    folder,video,scene,*_=project
    params=VideoParams(video_subject='History',video_script='Approved historical narration.',subtitle_enabled=False,bgm_type='')
    monkeypatch.setattr(task,'generate_script',lambda *a:params.video_script)
    monkeypatch.setattr(task,'generate_terms',lambda *a:['history'])
    monkeypatch.setattr(task,'save_script_data',lambda *a:None)
    monkeypatch.setattr(task,'generate_audio',lambda *a,**kw:('audio.mp3',4,None))
    monkeypatch.setattr(task,'generate_subtitle',lambda *a,**kw:'')
    monkeypatch.setattr(task,'get_video_materials',lambda *a,**kw:[str(scene)])
    monkeypatch.setattr(task,'generate_final_videos',lambda *a,**kw:([str(video)],[],[]))
    monkeypatch.setattr(task.sm,'state',MemoryState())
    service=task.upload_post.upload_post_service
    monkeypatch.setattr(service,'is_configured',lambda:True)
    monkeypatch.setattr(type(service),'auto_upload',property(lambda self:True))
    monkeypatch.setattr(type(service),'platforms',property(lambda self:['youtube']))
    schedule=Mock();monkeypatch.setattr(task,'_schedule_cross_post',schedule)
    result=task._run_pipeline('license-test',params)
    assert result['videos']==[str(video)] and result['cross_post_state'] is None
    schedule.assert_not_called()


def test_special_attribution_and_collection_credit_are_both_preserved(project):
    folder,video,_,_,data=project
    item=data['scenes']['scene_001']['candidates'][0]
    item['candidate']['metadata']['record']['imageinfo'][0]['extmetadata']['Attribution']={'value':'Additional named contributor credit'}
    manifest.save(folder,data)
    text=credits.prepare_description(video,'SEO')
    assert 'Museum collection, record 123' in text and 'Additional named contributor credit' in text


def test_malformed_metadata_is_pending_not_approved_or_a_crash():
    c=commons()
    c.metadata['record']['imageinfo'][0]['extmetadata']={'LicenseShortName':'Public domain'}
    assert classify(c)['classification']=='NEEDS_REVIEW'
    c.metadata['record']['imageinfo']=None
    assert classify(c)['classification']=='NEEDS_REVIEW'


def test_utf8_space_limit_protects_multibyte_descriptions(project):
    _,video,*_=project
    with pytest.raises(ArchiveError,match='excedem'):credits.prepare_description(video,'é'*3000)
