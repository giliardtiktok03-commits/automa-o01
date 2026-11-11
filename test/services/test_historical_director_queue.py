"""Durable sequential queue and recovery, with all model providers mocked offline."""
import json
from unittest.mock import Mock
from uuid import uuid4
import pytest
from app.models.autopilot import ChannelProfile
from app.models.autopilot_editorial import EditorialSnapshot
from app.models.historical_director import Request
from app.services.autopilot.repository import Repository
from app.services.autopilot import worker, editorial as ed
from app.services.historical_director import library, production, runner
from app.services.historical_director.repository import DirectorPaused
from app.services import channel_skills
from test.services.test_historical_director_analysis import proposal
from test.services.test_historical_director_production import brief


@pytest.fixture
def setup(tmp_path,monkeypatch):
    skills=tmp_path/'skills';skills.mkdir()
    monkeypatch.setattr(channel_skills,'_root',lambda:skills);library.install()
    tasks=tmp_path/'tasks';tasks.mkdir()
    monkeypatch.setattr(production.utils,'task_dir',lambda:str(tasks))
    profile=ChannelProfile(channel_id='history',name='History',language='en-US',auto_editorial=True,target_minutes=3,skill_ids=[library.SKILL_ID])
    snapshot=EditorialSnapshot(channel=profile,script_provider='openai',script_model='configured',skills=[channel_skills.load(library.SKILL_ID)])
    repo=Repository(tmp_path/'autopilot.sqlite3');repo.save_channel(profile);repo.set_enabled(True)
    return repo,snapshot


def analysis_result():
    data=proposal().model_dump()
    for i,angle in enumerate(data['alternatives']):angle.update(eligible=True,editorial_score=90-i,eligibility_reasons=['Reviewed evidence.'])
    return {'analysis':data,'recommended_ids':[a['angle_id'] for a in data['alternatives']],
            'visual_report':{'status':'no_images','images':[]}}


def analyzed(setup,**settings):
    repo,snapshot=setup
    request=Request(title='Original title',**settings)
    batch,_=repo.create_director_batch(request,snapshot)
    result=analysis_result()
    if not request.angle_enabled:
        result['analysis']['alternatives']=[]
        result['original_angle']={'angle_id':'original','eligible':True,'title_en':request.title,'title_pt':request.title,'name':'Original','core_question':'Original angle.'}
    assert worker.run_once(repo,lambda job:result)
    return batch,request


@pytest.mark.parametrize('count',[1,3,5])
def test_manual_selection_exact_count_order_and_idempotency(setup,count):
    repo,snapshot=setup;batch,_=analyzed(setup)
    selected=[f'angle_0{i}' for i in [5,3,1,4,2][:count]]
    ids,created=repo.enqueue_director_angles(batch,selected)
    assert created and len(ids)==count
    assert [r['angle_id'] for r in repo.director_items(batch) if r['role']=='production']==selected
    assert repo.enqueue_director_angles(batch,selected)==(ids,False)
    assert Repository(repo.path).enqueue_director_angles(batch,selected)==(ids,False)
    for item in repo.director_items(batch):
        if item['role']=='production':assert json.loads(repo.get_editorial(item['task_id'])['snapshot'])['channel']['language']=='en-US'


def test_empty_or_ineligible_selection_is_rejected(setup):
    repo,_=setup;batch,_=analyzed(setup)
    with pytest.raises(ValueError):repo.enqueue_director_angles(batch,[])
    with repo.connect() as db:
        value=analysis_result();value['analysis']['alternatives'][0]['eligible']=False
        db.execute('UPDATE director_batches SET analysis=?',(json.dumps(value),))
    with pytest.raises(ValueError,match='elegível'):repo.enqueue_director_angles(batch,['angle_01'])


@pytest.mark.parametrize('count',[1,5])
def test_automatic_default_one_and_explicit_five_survive_restart(setup,count):
    repo,_=setup
    batch,_=analyzed(setup,selection_mode='automatic',automatic_top_n=count,automatic_multiple=count>1)
    repo=Repository(repo.path);repo.prepare_director_automatic()
    items=[r for r in repo.director_items(batch) if r['role']=='production']
    assert len(items)==count
    assert [r['angle_id'] for r in items]==[f'angle_0{i}' for i in range(1,count+1)]
    repo.prepare_director_automatic();assert len(repo.director_items(batch))==count+1


def test_angle_disabled_preserves_title_and_produces_one(setup):
    repo,_=setup;batch,_=analyzed(setup,angle_enabled=False)
    repo.prepare_director_automatic()
    items=[r for r in repo.director_items(batch) if r['role']=='production']
    assert len(items)==1 and items[0]['title']=='Original title' and items[0]['angle_id']=='original'


def test_failure_pauses_batch_until_explicit_retry_or_cancel(setup):
    repo,_=setup;batch,_=analyzed(setup)
    ids,_=repo.enqueue_director_angles(batch,['angle_01','angle_02'])
    assert worker.run_once(repo,Mock(side_effect=ValueError('provider failed secret')))
    assert repo.director_batch(batch)['state']=='paused'
    assert not worker.run_once(repo,Mock())
    with pytest.raises(ValueError,match='Revise'):repo.resume_director(batch)
    assert repo.retry_editorial(ids[0],acknowledge_cost=True)
    assert repo.resume_director(batch)
    assert worker.run_once(repo,lambda job:{'published':False})
    assert worker.run_once(repo,lambda job:{'published':False})
    assert repo.director_batch(batch)['state']=='completed'
    assert 'secret' not in (repo.get_editorial(ids[0])['error'] or '')


def test_skip_policy_allows_next_after_recording_failure(setup):
    repo,_=setup;batch,_=analyzed(setup,on_failure='skip')
    ids,_=repo.enqueue_director_angles(batch,['angle_01','angle_02'])
    worker.run_once(repo,Mock(side_effect=RuntimeError('failed')))
    assert worker.run_once(repo,lambda job:{'published':False})
    assert repo.get_editorial(ids[1])['state']=='completed'
    assert repo.get_editorial(ids[0])['state']=='failed'


def test_pending_reorder_and_cancel_are_durable(setup):
    repo,_=setup;batch,_=analyzed(setup)
    ids,_=repo.enqueue_director_angles(batch,['angle_01','angle_02','angle_03'])
    repo.reorder_director(batch,list(reversed(ids)))
    assert [r['task_id'] for r in repo.director_items(batch) if r['role']=='production']==list(reversed(ids))
    assert repo.cancel_director_item(ids[2])
    handler=Mock(return_value={'published':False})
    assert worker.run_once(Repository(repo.path),handler)
    assert handler.call_args.args[0]['task_id']==ids[1]
    assert repo.get_editorial(ids[2])['state']=='cancelled'


def test_pause_at_safe_boundary_preserves_finished_stage(setup):
    repo,_=setup;batch,_=analyzed(setup)
    ids,_=repo.enqueue_director_angles(batch,['angle_01','angle_02'])
    def first(job):
        ed.step(repo,job['task_id'],'paid_finished',lambda:{'receipt':'persisted'})
        repo.pause_director(batch)
        production.ControlledStages(repo,job['task_id']).begin_stage(job['task_id'],'next',remote=True)
    assert worker.run_once(repo,first)
    assert repo.get_editorial(ids[0])['state']=='paused'
    assert not worker.run_once(repo,Mock())
    repo.resume_director(batch)
    paid=Mock()
    def resumed(job):
        assert ed.step(repo,job['task_id'],'paid_finished',paid)=={'receipt':'persisted'}
        return {'published':False}
    assert worker.run_once(repo,resumed)
    paid.assert_not_called()


def test_batch_identity_and_channel_settings_are_isolated(setup):
    repo,snapshot=setup;req=Request(title='Original title')
    batch,created=repo.create_director_batch(req,snapshot)
    assert created and repo.create_director_batch(req,snapshot)==(batch,False)
    assert repo.create_director_batch(req,snapshot,new_version=True)[0]!=batch
    repo.save_director_profile('history',{'central_angle':'Documented decisions','visual_identity':'Warm maps'})
    other=snapshot.channel.model_copy(update={'channel_id':'other'})
    repo.save_channel(other)
    assert repo.director_profile('other')=={}
    assert repo.director_profile('history')['central_angle']=='Documented decisions'


def test_five_jobs_research_and_export_five_independent_packages(setup,monkeypatch):
    repo,_=setup;batch,_=analyzed(setup)
    ids,_=repo.enqueue_director_angles(batch,[f'angle_0{i}' for i in range(1,6)])
    research={'summary':'Independent synthetic research for every selected documentary angle.','ready':True,'gaps':[],
        'sources':[{'id':'S1','title':'Archive','url':'https://archive.example/'},{'id':'S2','title':'Museum','url':'https://museum.example/'}],
        'claims':[{'id':f'C{i}','statement':'Synthetic documented historical statement '+str(i),
                   'evidence':[{'source_id':'S1','text':'A synthetic documented passage for testing.'}]} for i in range(1,5)]}
    search=Mock(side_effect=lambda title,snapshot:{'report':research,'receipt':title})
    monkeypatch.setattr(ed,'search',search)
    monkeypatch.setattr(ed,'read_sources',lambda report,snapshot:{s['id']:{**s,'text':'Source text','sha256':'a'*64} for s in report['sources']})
    monkeypatch.setattr(ed,'review',lambda *a,**kw:{'approved':True,'issues':[]})
    monkeypatch.setattr(ed,'plan',lambda *a:{'required':False})
    def script(title,snapshot,report,skills):
        code=title.split()[-1]
        text=' '.join(code+'word'+str(i) for i in range(400))
        return {'document':{'title':title},'narration':text,'word_count':400,'effective_skills':[s.model_dump() for s in skills]}
    monkeypatch.setattr(ed,'script',script)
    monkeypatch.setattr(ed,'package',lambda title,*a:{'description':title+'\n\nReferences\nhttps://archive.example/','tags':[title],'hashtags':['#history'],'thumbnail_brief':'Original concept for '+title})
    def concepts(snapshot,angle,*a):
        value=brief().model_dump()
        for concept in value['concepts']:concept['name']+=' '+angle['angle_id']
        return value
    monkeypatch.setattr(production,'thumbnails',concepts)
    for _ in ids:assert worker.run_once(Repository(repo.path))
    assert not worker.run_once(repo)
    assert search.call_count==5
    results=[json.loads(repo.get_editorial(task)['result']) for task in ids]
    assert len({r['script'] for r in results})==5
    assert len({r['metadata']['description'] for r in results})==5
    assert len({r['thumbnail_concepts']['concepts'][0]['name'] for r in results})==5
    assert all(r['quality_report']['approved'] and not r['published'] for r in results)
    assert all(production.archive(r) for r in results)
    assert repo.director_batch(batch)['state']=='completed'


def test_two_process_workers_cannot_run_two_director_jobs(setup):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    repo,_=setup;batch,_=analyzed(setup)
    repo.enqueue_director_angles(batch,['angle_01','angle_02'])
    entered,release=threading.Event(),threading.Event()
    def hold(job):
        entered.set();assert release.wait(5)
        return {'published':False}
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(worker.run_once,repo,hold)
        assert entered.wait(5)
        assert not worker.run_once(Repository(repo.path),hold)
        release.set();assert first.result()
    assert worker.run_once(repo,lambda job:{'published':False})


def test_real_process_crash_never_repeats_unknown_paid_analysis(setup,monkeypatch):
    import subprocess,sys
    from pathlib import Path
    repo,snapshot=setup
    batch,_=repo.create_director_batch(Request(title='Original title'),snapshot)
    task=repo.director_items(batch)[0]['task_id']
    code='''
import os,sys
from app.services.autopilot.repository import Repository
from app.services.autopilot.worker import run_once
repo=Repository(sys.argv[1])
def crash(job):
    repo.begin_stage(job['task_id'],'director_research',remote=True)
    os._exit(23)
run_once(repo,crash)
'''
    result=subprocess.run([sys.executable,'-c',code,str(repo.path)],cwd=Path(__file__).parents[2],timeout=30)
    assert result.returncode==23
    paid=Mock(side_effect=AssertionError('Must not submit twice'))
    monkeypatch.setattr(ed,'search',paid)
    assert worker.run_once(Repository(repo.path))
    assert repo.get_editorial(task)['state']=='blocked' and repo.director_batch(batch)['state']=='paused'
    paid.assert_not_called()


def test_reference_replacement_is_versioned_and_only_before_start(setup,monkeypatch,tmp_path):
    from app.services.historical_director import images
    from test.services.test_historical_director_analysis import picture
    image_dir=tmp_path/'images';image_dir.mkdir();monkeypatch.setattr(images,'root',lambda:image_dir)
    refs=images.upload([picture()])
    repo,_=setup;batch,_=analyzed(setup)
    ids,_=repo.enqueue_director_angles(batch,['angle_01'])
    repo.replace_director_references(ids[0],refs,True)
    item=Repository(repo.path).director_item(ids[0]);context=json.loads(item['context'])
    assert item['angle_version']==2 and context['request']['thumbnails'][0]['image_id']==refs[0].image_id
    assert context['visual_override']
    assert repo.get_editorial(ids[0])['identity_hash'].endswith(':2')
    repo.take_editorial()
    with pytest.raises(ValueError,match='pendente'):repo.replace_director_references(ids[0],[],False)


def test_retry_limit_and_cancel_release_the_director_queue(setup):
    repo,_=setup;batch,_=analyzed(setup)
    ids,_=repo.enqueue_director_angles(batch,['angle_01'])
    handler=Mock(side_effect=RuntimeError('unavailable'))
    for i in range(4):
        assert worker.run_once(repo,handler)
        if i<3:
            repo.retry_editorial(ids[0],acknowledge_cost=True);repo.resume_director(batch)
    with pytest.raises(ValueError,match='Limite de 3'):repo.retry_editorial(ids[0],acknowledge_cost=True)
    repo.cancel_director_batch(batch)
    assert repo.director_batch(batch)['state']=='completed'
    assert repo.get_editorial(ids[0])['state']=='cancelled'
