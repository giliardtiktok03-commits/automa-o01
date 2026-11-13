"""No paid calls: public discovery, exact evidence, OAuth routing and checkpoints."""
import hashlib
import json
from unittest.mock import Mock

import pytest
from app.models.autopilot import ChannelProfile
from app.models.autopilot_editorial import Research, Review, Script, Package
from app.models.historical_director import Request, ReferenceOverview, ThumbnailBrief
from app.services.autopilot import editorial as ed, public_research as public, sources, worker
from app.services.autopilot.recovery import RecoveryBlocked
from app.services.autopilot.repository import Repository
from app.services.historical_director import runner
from app.services import llm, codex_oauth, chatgpt_oauth
from test.services.test_autopilot_editorial import report, snapshot, QUOTE
from test.services.test_historical_director_queue import setup
from test.services.test_historical_director_production import brief


@pytest.fixture
def login(snapshot,monkeypatch):
    snapshot.channel.research_backend='public_login'
    snapshot.script_provider='openai_codex'
    monkeypatch.setattr(codex_oauth,'account_status',lambda:True)
    monkeypatch.setattr(chatgpt_oauth,'account_status',lambda:True)
    monkeypatch.setattr(ed,'research_key',Mock(side_effect=AssertionError('No API key allowed')))
    monkeypatch.setattr(ed,'OpenAI',Mock(side_effect=AssertionError('No OpenAI API allowed')))
    return snapshot


def pages(report):
    return {'pages':[{**s,'text':QUOTE+' Extra retrieved text for the audit trail.',
        'resolved_url':s['url'],'sha256':'a'*64,'retrieved_at':'test'} for s in report['sources']]}


def discovered(report):
    return {'index':'wikimedia_mediawiki','candidates':[{'candidate_id':i,'url':s['url'],
        'title':s['title'],'discovered_via':'external_reference'} for i,s in enumerate(report['sources'],1)]}


def test_prepare_login_does_not_require_api_key(login,monkeypatch):
    frozen=ed.prepare(login.channel.model_copy(update={'script_provider':'openai_codex','skill_ids':[]}),
        app_settings={'llm_provider':'openai_codex','openai_codex_model_name':'configured-model'})
    assert frozen.channel.research_backend=='public_login'
    assert frozen.script_provider=='openai_codex' and frozen.script_model=='configured-model'
    ed.research_key.assert_not_called()
    monkeypatch.setattr(codex_oauth,'account_status',lambda:False)
    with pytest.raises(RecoveryBlocked,match='Conecte'):public.require_login('openai_codex')
    with pytest.raises(RecoveryBlocked,match='exige selecionar'):public.require_login('openai')


def test_legacy_api_search_cannot_be_called_in_login_mode(login):
    with pytest.raises(RecoveryBlocked,match='etapas persistidas'):ed.search('Title',login)
    ed.OpenAI.assert_not_called()


def test_discovery_uses_only_real_public_results_and_filters_domains(monkeypatch):
    wiki=Mock(side_effect=[{'query':{'search':[{'pageid':1,'title':'History'}]}},
        {'query':{'pages':{'1':{'title':'History','fullurl':'https://en.wikipedia.org/wiki/History',
            'extlinks':[{'*':'https://archive.example/record'},{'*':'https://museum.example/record'},
                        {'*':'http://insecure.example/'},{'*':'https://youtube.com/watch?v=1'}]}}}}])
    monkeypatch.setattr(public,'wiki',wiki)
    result=public.discover({'queries':['Specific historical event']},['archive.example','museum.example'])
    assert [r['url'] for r in result['candidates']]==['https://archive.example/record','https://museum.example/record']
    assert wiki.call_count==2


def test_unknown_source_selection_rejected_before_fetch(login,report,monkeypatch):
    monkeypatch.setattr(ed,'text',lambda *a,**kw:public.Selection(candidate_ids=[1,999]))
    with pytest.raises(RecoveryBlocked,match='desconhecidos'):public.select('Title',login,discovered(report))


def test_read_skips_unreadable_and_requires_distinct_resolved_hosts(report,monkeypatch):
    selected={'candidates':discovered(report)['candidates']}
    monkeypatch.setattr(sources,'fetch',Mock(side_effect=[RecoveryBlocked('Unavailable'),pages(report)['pages'][1]]))
    with pytest.raises(RecoveryBlocked,match='dois domínios'):public.read(selected,[])
    monkeypatch.setattr(sources,'fetch',Mock(side_effect=[{**p,'resolved_url':'https://same.example/page'} for p in pages(report)['pages']]))
    with pytest.raises(RecoveryBlocked,match='dois domínios'):public.read(selected,[])


@pytest.mark.parametrize('failure',['invented_url','invented_quote','irrelevant','one_host'])
def test_dossier_cannot_claim_sources_or_quotes_that_were_not_read(report,failure):
    read=pages(report)
    if failure=='invented_url':report['sources'][0]['url']='https://invented.example/fake'
    if failure=='invented_quote':report['claims'][0]['evidence'][0]['text']='This fabricated quote is not in any fetched source.'
    if failure=='irrelevant':report.update(ready=False,gaps=['No evidence supports the title'])
    if failure=='one_host':read['pages'][1]['resolved_url']=read['pages'][0]['resolved_url']
    with pytest.raises(RecoveryBlocked):public.validate({'report':report},read,[])


def test_pipeline_reopens_journal_without_repeating_login_calls(login,report,tmp_path,monkeypatch):
    repo=Repository(tmp_path/'journal.sqlite3');repo.save_channel(login.channel);repo.set_enabled(True)
    task_id,_=repo.submit_editorial('Original title',login)
    calls=[]
    def text(prompt,snapshot,*,output,**kwargs):
        calls.append(output.__name__)
        if output==public.Queries:return public.Queries(queries=['Specific historical event'])
        if output==public.Selection:return public.Selection(candidate_ids=[1,2])
        return Research.model_validate(report)
    monkeypatch.setattr(ed,'text',text)
    discovery=Mock(return_value=discovered(report));read=Mock(return_value=pages(report))
    monkeypatch.setattr(public,'discover',discovery);monkeypatch.setattr(public,'read',read)
    first=public.run(repo,task_id,'search','Original title',login)
    second=public.run(Repository(repo.path),task_id,'search','Original title',login)
    assert first==second and calls==['Queries','Selection','Research']
    assert discovery.call_count==read.call_count==1
    assert set(repo.stages(task_id))=={'search_queries','search_discovery','search_selection','search_pages','search_dossier','search'}
    assert first['research_backend']=='public_login'
    assert first['retrieved']['S1']['sha256']=='a'*64


def test_interrupted_login_stage_blocks_without_repeat(login,tmp_path,monkeypatch):
    repo=Repository(tmp_path/'journal.sqlite3');repo.save_channel(login.channel)
    task_id,_=repo.submit_editorial('Original title',login)
    repo.begin_stage(task_id,'search_queries',remote=True)
    remote=Mock();monkeypatch.setattr(ed,'text',remote)
    with pytest.raises(RecoveryBlocked,match='remota'):public.run(repo,task_id,'search','Original title',login)
    remote.assert_not_called()


def test_visual_analysis_is_blocked_before_any_research_request(login):
    request=Request(title='Original title',thumbnail_reference_enabled=True,
        thumbnails=[{'image_id':'a'*64,'width':100,'height':100}])
    with pytest.raises(RecoveryBlocked,match='análise visual'):runner.check_research_options(request,login)
    ed.OpenAI.assert_not_called()


def test_end_to_end_original_angle_export_without_openai_key(setup,report,monkeypatch):
    repo,snapshot=setup
    snapshot.channel.research_backend='public_login'
    snapshot.script_provider='openai_codex'
    repo.save_channel(snapshot.channel,expected_version=1)
    monkeypatch.setattr(codex_oauth,'account_status',lambda:True)
    monkeypatch.setattr(ed,'OpenAI',Mock(side_effect=AssertionError('No API calls')))
    monkeypatch.setattr(ed,'research_key',Mock(side_effect=AssertionError('No API key')))
    monkeypatch.setattr(public,'discover',lambda *a:discovered(report))
    monkeypatch.setattr(public,'read',lambda *a:pages(report))
    calls=[]
    def text(prompt,frozen,*,output=Review,**kwargs):
        calls.append(output.__name__)
        assert frozen.script_provider=='openai_codex'
        if output==public.Queries:return public.Queries(queries=['Specific historical event'])
        if output==public.Selection:return public.Selection(candidate_ids=[1,2])
        if output==Research:return Research.model_validate(report)
        if output==Review:return Review(approved=True,issues=[])
        if output==ReferenceOverview:return ReferenceOverview(theme='Independent documented theme',reference_angle='The exact original historical angle',reference_structure=['Title only; no reference script.'])
        if output==Script:return Script(title='Original title',sections=[{'narration':' '.join('unique'+str(i) for i in range(n,n+135)), 'claim_ids':['C1']} for n in [0,135,270]])
        if output==Package:return Package(description='Original documented introduction to this historical event.',tags=['history'],hashtags=['#history'],thumbnail_brief='Original truthful concept based on the supplied historical evidence.')
        if output==ThumbnailBrief:return brief()
        raise AssertionError(output)
    monkeypatch.setattr(ed,'text',text)
    batch,_=repo.create_director_batch(Request(title='Original title',angle_enabled=False),snapshot)
    assert worker.run_once(repo)
    assert worker.run_once(repo)  # auto-enqueues the original angle
    items=[r for r in repo.director_items(batch) if r['role']=='production']
    assert len(items)==1 and items[0]['state']=='completed',items
    result=json.loads(items[0]['result'])
    assert len(result['thumbnail_concepts']['concepts'])==3
    assert 'References' in result['metadata']['description']
    assert result['word_count']==405 and result['quality_report']['approved']
    assert not result['published'] and not result['video_generated']
    assert calls.count('Research')==2  # independent analysis and production dossiers
    ed.OpenAI.assert_not_called();ed.research_key.assert_not_called()


@pytest.mark.parametrize('status',[403,429,503])
def test_public_index_denied_or_limited_has_no_paid_fallback(status,monkeypatch):
    response=Mock(status_code=status)
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    request=Mock(return_value=response);monkeypatch.setattr(public.requests,'get',request)
    paid=Mock();monkeypatch.setattr(ed,'OpenAI',paid)
    with pytest.raises(RecoveryBlocked,match='indisponível ou limitada'):public.wiki({'action':'query'})
    assert request.call_count==1 and request.call_args.args[0]==public.WIKI
    assert request.call_args.kwargs['allow_redirects'] is False
    assert 'Authorization' not in request.call_args.kwargs['headers']
    paid.assert_not_called()
