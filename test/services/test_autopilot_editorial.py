"""Offline contracts: no API requests or billable generation in this suite."""
import json
import socket
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.models.autopilot import ChannelProfile
from app.models.autopilot_editorial import EditorialSnapshot, Research
from app.services.autopilot import editorial as ed, sources, worker
from app.services.autopilot.recovery import RecoveryBlocked
from app.services.autopilot.repository import Repository, Conflict

QUOTE = 'The original record explicitly documents this particular event.'


@pytest.fixture
def report():
    return Research(summary='Four documented statements for an evidence-based narrative.', ready=True,
        sources=[{'id':'S1','title':'Archive','url':'https://archive.example/record'},
                 {'id':'S2','title':'Museum','url':'https://museum.example/record'}],
        claims=[{'id':f'C{i}','statement':f'Documented statement number {i}.',
                 'evidence':[{'source_id':'S1' if i%2 else 'S2','text':QUOTE}]} for i in range(1,5)]).model_dump()


@pytest.fixture
def snapshot():
    return EditorialSnapshot(channel=ChannelProfile(channel_id='history',name='History',target_minutes=3,auto_editorial=True),
                             script_provider='openai',script_model='configured-model')


@pytest.fixture
def repo(tmp_path, snapshot):
    value=Repository(tmp_path/'journal.sqlite3')
    value.save_channel(snapshot.channel)
    value.set_enabled(True)
    return value


def enqueue(repo, snapshot):
    return repo.submit_editorial('Original title',snapshot)[0]


def test_duplicate_title_and_channel_isolation(repo,snapshot):
    first=enqueue(repo,snapshot)
    assert repo.submit_editorial(' ORIGINAL   title ',snapshot)==(first,False)
    second=snapshot.model_copy(deep=True)
    second.channel.channel_id='another'
    repo.save_channel(second.channel)
    assert repo.submit_editorial('Original title',second)[0]!=first
    assert len(repo.editorial_jobs())==2


def test_disabled_channel_or_global_worker_never_runs(repo,snapshot):
    enqueue(repo,snapshot)
    handler=Mock()
    repo.set_enabled(False)
    assert not worker.run_once(repo,handler)
    repo.set_enabled(True)
    disabled=snapshot.channel.model_copy(update={'auto_editorial':False})
    repo.save_channel(disabled,expected_version=1)
    assert not worker.run_once(repo,handler)
    handler.assert_not_called()


def test_completed_stage_reused_and_tampered_artifact_blocked(repo,snapshot):
    task=enqueue(repo,snapshot)
    paid=Mock(return_value={'answer':'receipt'})
    assert ed.step(repo,task,'search',paid)=={'answer':'receipt'}
    assert ed.step(Repository(repo.path),task,'search',paid)=={'answer':'receipt'}
    paid.assert_called_once()
    with repo.connect() as db:
        db.execute("UPDATE editorial_stages SET result='{}'")
    with pytest.raises(RecoveryBlocked,match='alterado'):
        ed.step(repo,task,'search',paid)
    paid.assert_called_once()


def test_interrupted_remote_blocks_but_local_operation_can_resume(repo,snapshot):
    task=enqueue(repo,snapshot)
    repo.begin_stage(task,'search',remote=True)
    paid=Mock()
    with pytest.raises(RecoveryBlocked,match='interrompida'):
        ed.step(Repository(repo.path),task,'search',paid)
    paid.assert_not_called()
    repo.begin_stage(task,'sources',remote=False)
    assert ed.step(repo,task,'sources',lambda:{'local':'safe'},remote=False)=={'local':'safe'}


def test_failed_review_can_only_retry_with_explicit_cost_ack(repo,snapshot):
    task=enqueue(repo,snapshot)
    repo.take_editorial()
    ed.step(repo,task,'search',lambda:{'receipt':'saved'})
    with pytest.raises(RecoveryBlocked):
        ed.step(repo,task,'evidence_review',lambda:ed.require_approval({'approved':False,'issues':['unsupported']}))
    repo.finish_editorial(task,'blocked')
    with pytest.raises(Conflict):
        repo.retry_editorial(task)
    assert repo.retry_editorial(task,acknowledge_cost=True)
    assert set(repo.stages(task))=={'search'}
    assert json.loads(repo.get_editorial(task)['snapshot'])==snapshot.model_dump()
    with repo.connect() as db:
        assert db.execute('SELECT count(*) FROM editorial_history').fetchone()[0]==1


def test_official_search_requires_real_tool_citations(monkeypatch,snapshot,report):
    payload={'id':'receipt','status':'completed','usage':{},'output':[
        {'type':'web_search_call','status':'completed','action':{'sources':[{'url':s['url']} for s in report['sources']]+[{'url':'http://unselected.example/'}]}},
        {'type':'message','content':[{'type':'output_text','text':json.dumps(report),'annotations':[]}]}]}
    client=Mock()
    client.responses.create.return_value.model_dump.return_value=payload
    sdk=Mock()
    sdk.return_value.__enter__=Mock(return_value=client)
    sdk.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr(ed,'OpenAI',sdk)
    monkeypatch.setattr(ed,'research_key',lambda:'fake-key')
    result=ed.search('Original title',snapshot)
    assert result['request_id']=='receipt'
    args=client.responses.create.call_args.kwargs
    assert args['tools'][0]['type']=='web_search' and args['store'] is False
    assert sdk.call_args.kwargs['max_retries']==0
    payload['output'][0]['action']['sources']=[]
    with pytest.raises(RecoveryBlocked,match='confirmou'):
        ed.search('Original title',snapshot)


def test_fabricated_url_and_insufficient_evidence_block_search(monkeypatch,snapshot,report):
    payload={'status':'completed','output':[{'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://different.example/'}]}},
        {'type':'message','content':[{'type':'output_text','text':json.dumps(report)}]}]}
    client=Mock(); client.responses.create.return_value.model_dump.return_value=payload
    sdk=Mock();sdk.return_value.__enter__=Mock(return_value=client);sdk.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr(ed,'OpenAI',sdk);monkeypatch.setattr(ed,'research_key',lambda:'fake')
    with pytest.raises(RecoveryBlocked,match='não confirmada'):
        ed.search('Title',snapshot)
    report['ready']=False
    payload['output'][1]['content'][0]['text']=json.dumps(report)
    with pytest.raises(RecoveryBlocked,match='insuficientes'):
        ed.search('Title',snapshot)


def test_quotes_must_exist_in_downloaded_text(monkeypatch,snapshot,report):
    monkeypatch.setattr(sources,'fetch',lambda url,domains:{'url':url,'resolved_url':url,'text':QUOTE+' More context.','sha256':'a'*64})
    assert set(ed.read_sources(report,snapshot))=={'S1','S2'}
    report['claims'][0]['evidence'][0]['text']='A completely fabricated quotation never present in the record.'
    with pytest.raises(RecoveryBlocked,match='não foi encontrado'):
        ed.read_sources(report,snapshot)


def test_reader_rejects_private_dns_and_unsafe_urls(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    for url in ['http://archive.example','https://user:pass@archive.example','https://localhost/x','https://archive.example:444/']:
        with pytest.raises(RecoveryBlocked):sources.canonical(url)
    with pytest.raises(RecoveryBlocked,match='público'):
        sources.check_public('https://archive.example')
    assert sources.allowed('https://sub.archive.example/x',['archive.example'])
    assert not sources.allowed('https://archive.example.attacker.test/',['archive.example'])


def test_reader_bounds_content_and_redirect_domains(monkeypatch):
    response=Mock(status_code=200,headers={'Content-Type':'text/html'},encoding='utf-8')
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.iter_content.return_value=[('<script>secret instruction</script><p>'+QUOTE*5+'</p>').encode()]
    get=Mock(return_value=response)
    monkeypatch.setattr(sources.requests,'get',get);monkeypatch.setattr(sources,'check_public',lambda url:None)
    result=sources.fetch('https://archive.example/')
    assert 'secret instruction' not in result['text'] and len(result['sha256'])==64
    assert get.call_args.kwargs['allow_redirects'] is False
    response.iter_content.return_value=[b'x'*(sources.MAX_BYTES+1)]
    with pytest.raises(RecoveryBlocked,match='limite'):sources.fetch('https://archive.example/')
    response.status_code=302;response.headers={'Location':'https://outside.example/'}
    with pytest.raises(RecoveryBlocked,match='domínios'):sources.fetch('https://archive.example/',['archive.example'])


def test_pipeline_reviews_output_and_never_regenerates_completed_steps(monkeypatch,repo,snapshot,report):
    task=enqueue(repo,snapshot)
    calls={}
    def patch(name,value):
        calls[name]=Mock(return_value=value);monkeypatch.setattr(ed,name,calls[name])
    patch('search',{'report':report})
    patch('read_sources',{s['id']:{**s,'text':QUOTE,'sha256':'a'*64} for s in report['sources']})
    patch('review',{'approved':True,'issues':[]})
    patch('plan',{'required':False})
    patch('script',{'document':{'title':'Original title'},'narration':'Spoken script','word_count':300,'effective_skills':[]})
    patch('package',{'description':'Intro\nReferences','tags':['history'],'hashtags':['#history'],'thumbnail_brief':'A factual visual promise.'})
    # Simulate process death after result stages were saved but before job finish.
    repo.take_editorial()
    saved=ed.run(repo.get_editorial(task),repo)
    assert saved['published'] is False and saved['video_generated'] is False
    assert calls['review'].call_count==3
    assert worker.run_once(Repository(repo.path))
    assert repo.get_editorial(task)['state']=='completed'
    for name,call in calls.items():assert call.call_count==(3 if name=='review' else 1)
    assert not worker.run_once(repo)
    assert not repo.retry_editorial(task,acknowledge_cost=True)


def test_migration_keeps_v1_profiles_recovery_and_queue_settings(tmp_path):
    path=tmp_path/'old.sqlite3'
    repo=Repository(path)
    profile=ChannelProfile(channel_id='old',name='Old',auto_resume=True)
    repo.save_channel(profile);repo.set_enabled(True)
    repo.enroll('2d6613a1-c254-484c-a078-4d43f05283fa','old','Existing title','a'*64)
    with repo.connect() as db:
        for table in ['editorial_history','editorial_stages','editorial_jobs']:db.execute('DROP TABLE '+table)
        value=profile.model_dump()
        for key in ['auto_editorial','target_minutes','research_model','research_domains','script_provider','script_model']:value.pop(key)
        db.execute('UPDATE channels SET profile=?',(json.dumps(value),))
        db.execute('PRAGMA user_version=1')
    migrated=Repository(path)
    assert migrated.enabled() and len(migrated.jobs())==1
    assert not ChannelProfile.model_validate({k:v for k,v in migrated.channels()[0].items() if k!='version'}).auto_editorial
    assert migrated.get(migrated.jobs()[0]['task_id'])['title']=='Existing title'
    with migrated.connect() as db:assert db.execute('PRAGMA user_version').fetchone()[0]==2


def test_metadata_validates_and_appends_all_verified_sources(monkeypatch,snapshot,report):
    from app.models.autopilot_editorial import Package
    value={'description':'A coherent introductory description for the documented story.', 'tags':['history','history'], 'hashtags':['#history'], 'thumbnail_brief':'A factual archive document with a coherent promise.'}
    monkeypatch.setattr(ed,'text',lambda *a,**kw:Package.model_validate(value))
    result=ed.package('Title',snapshot,report,{'narration':'script'},[])
    assert result['tags']==['history']
    assert result['description'].endswith('Museum — https://museum.example/record')
    value['tags']=['###']
    with pytest.raises(RecoveryBlocked,match='Tags vazias'):ed.package('Title',snapshot,report,{'narration':'script'},[])


def test_source_validation_and_reviews_are_strict(report):
    report['claims'][0]['evidence'][0]['source_id']='S9'
    with pytest.raises(ValidationError):Research.model_validate(report)
    for value in [{'approved':'yes','issues':[]},{'approved':True,'issues':['Not supported']}]:
        with pytest.raises(ValidationError):ed.require_approval(value)


def test_selected_skills_are_frozen_in_order_and_credentials_stay_out(monkeypatch,repo,snapshot):
    import hashlib
    from app.models.channel_skill import ChannelSkillSnapshot
    from app.services import channel_skills, channel_skill_runtime
    library={name:ChannelSkillSnapshot(skill_id=name,name=name,content='Original '+name,
        sha256=hashlib.sha256(('Original '+name).encode()).hexdigest()) for name in ['primary','extra']}
    monkeypatch.setattr(channel_skills,'load',lambda name:library[name])
    monkeypatch.setattr(ed,'research_key',lambda:'private-key')
    profile=snapshot.channel.model_copy(update={'skill_ids':['primary','extra']})
    repo.save_channel(profile,expected_version=1)
    frozen=ed.prepare(profile,app_settings={'llm_provider':'openai','openai_api_key':'private-key','openai_model_name':'configured-model'})
    task=enqueue(repo,frozen)
    library['primary']=library['primary'].model_copy(update={'content':'Changed later'})
    persisted=EditorialSnapshot.model_validate_json(repo.get_editorial(task)['snapshot'])
    assert [s.skill_id for s in persisted.skills]==['primary','extra']
    assert persisted.skills[0].content=='Original primary'
    assert channel_skill_runtime.validate(persisted.skills)
    assert 'private-key' not in repo.get_editorial(task)['snapshot']


def test_beyond_blueprint_requires_explicit_review_of_every_beat(monkeypatch,tmp_path,snapshot):
    from app.services import story_intelligence as story, channel_skills as library
    from app.models.story_intelligence import EditorialClaim
    monkeypatch.setattr(library,'_root',lambda:tmp_path)
    story.install()
    skill=library.load(story.SKILL_ID)
    snapshot.channel.skill_ids=[story.SKILL_ID];snapshot.skills=[skill]
    title='Operation Gold: The Spy Tunnel Beneath Berlin'
    bp=story.analyze(title,use_model=False,app_config={})
    from app.models.story_intelligence import Source
    bp.source_register=[Source(id='S1',title='Synthetic test record',excerpt=QUOTE,interpretation='documented',provenance='autopilot_retrieved')]
    bp.claim_register=[EditorialClaim(statement='A synthetic documented statement for this test.',classification='documented_fact',source_ids=['S1'],evidence_quotes=[{'source_id':'S1','excerpt':QUOTE}])]
    for beat in bp.narrative_beats:beat.source_ids=['S1']
    planned={'required':True,'blueprint':bp.model_dump()}
    with pytest.raises(RecoveryBlocked,match='todos os beats'):
        ed.effective_skills(title,snapshot,planned,{'approved':True,'issues':[],'approved_beats':[1]})
    result=ed.effective_skills(title,snapshot,planned,{'approved':True,'issues':[],'approved_beats':list(range(1,len(bp.narrative_beats)+1))})
    story.require_script_ready(title,result)
    assert story.MARKER in result[0].content
    assert story.MARKER not in library.load(story.SKILL_ID).content


def test_missing_research_key_blocks_without_billable_calls(monkeypatch):
    from app.config import config
    monkeypatch.setattr(config,'snapshot_config_with_pending',lambda _: {})
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(RecoveryBlocked,match='Login ChatGPT/Codex'):
        ed.research_key()


def test_process_crash_during_paid_stage_does_not_submit_again(repo,snapshot,monkeypatch):
    import subprocess
    import sys
    from pathlib import Path
    task=enqueue(repo,snapshot)
    code='''
import os,sys
from app.services.autopilot.repository import Repository
from app.services.autopilot.worker import run_once
repo=Repository(sys.argv[1])
def crash(job):
    repo.begin_stage(job['task_id'],'search',remote=True)
    os._exit(23)
run_once(repo,crash)
'''
    result=subprocess.run([sys.executable,'-c',code,str(repo.path)],cwd=Path(__file__).parents[2],timeout=30)
    assert result.returncode==23
    assert Repository(repo.path).get_editorial(task)['state']=='running'
    paid=Mock(side_effect=AssertionError('A second request must not be made'))
    monkeypatch.setattr(ed,'search',paid)
    assert worker.run_once(Repository(repo.path))
    assert repo.get_editorial(task)['state']=='blocked'
    paid.assert_not_called()


def test_blueprint_review_without_full_coverage_fails_the_retryable_stage(repo,snapshot,monkeypatch):
    task=enqueue(repo,snapshot)
    monkeypatch.setattr(ed,'review',lambda *a,**kw:{'approved':True,'issues':[],'approved_beats':[1]})
    with pytest.raises(RecoveryBlocked,match='todos os beats'):
        ed.step(repo,task,'blueprint_review',lambda:ed.review_blueprint('Title',snapshot,{'blueprint':{'narrative_beats':[{},{}]}}))
    assert repo.stages(task)['blueprint_review']['state']=='failed'
