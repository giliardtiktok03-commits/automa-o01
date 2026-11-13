"""Coarena uses the existing OpenAI SDK transport, no live key or billable calls."""
import json
from unittest.mock import Mock, patch
import httpx
import pytest
from openai import OpenAI
from app.config import config
from app.models.llm_provider import get_llm_provider
from app.models.autopilot import ChannelProfile
from app.services import llm
from app.services.autopilot import editorial as ed, public_research as public
from app.services.autopilot.recovery import RecoveryBlocked
from test.services.test_autopilot_editorial import snapshot, report
from test.services.test_public_login_research import pages, discovered


@pytest.mark.parametrize('configured_model,expected_model',[('', 'claude-fable-5'),('claude-sonnet-5-5','claude-sonnet-5-5')])
def test_exact_coarena_protocol_and_model_without_global_changes(configured_model,expected_model):
    previous=dict(config.app);calls=[]
    def respond(request):
        calls.append(request)
        assert str(request.url)=='https://coarena.ai/api/v1/chat/completions'
        assert request.headers['Authorization']=='Bearer simulated-coarena-key'
        assert json.loads(request.content)=={'model':expected_model,'messages':[{'role':'user','content':'Historical research prompt'}]}
        return httpx.Response(200,json={'id':'simulated','object':'chat.completion','created':0,'model':expected_model,
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'Documented response'}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        with OpenAI(api_key='simulated-coarena-key',base_url='https://coarena.ai/api/v1',http_client=transport,max_retries=0) as client:
            with patch.object(llm,'OpenAI',return_value=client) as factory:
                result=llm._generate_response('Historical research prompt',app_config={'llm_provider':'coarena',
                    'coarena_api_key':'simulated-coarena-key','coarena_model_name':configured_model},max_retries=0)
                assert factory.call_args.kwargs['base_url']=='https://coarena.ai/api/v1'
    assert result=='Documented response' and len(calls)==1
    assert dict(config.app)==previous


def test_catalog_preserves_existing_anthropic_and_no_key_request():
    provider=get_llm_provider('coarena')
    assert provider.adapter=='openai_compatible' and provider.default_model=='claude-fable-5'
    assert provider.default_base_url=='https://coarena.ai/api/v1'
    assert get_llm_provider('anthropic').default_base_url=='https://api.anthropic.com/v1/'
    with patch.object(llm,'OpenAI') as client:
        result=llm._generate_response('No key configured',app_config={'llm_provider':'coarena'})
    assert result.startswith('Error:') and 'api_key is not set' in result
    client.assert_not_called()


@pytest.mark.parametrize('status',[401,403,429,500])
def test_http_errors_never_become_script_or_retry_without_authorization(status):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(status,json={'error':{'message':'simulated upstream failure','type':'api_error'}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        with OpenAI(api_key='simulated-key',base_url='https://coarena.ai/api/v1',http_client=transport,max_retries=0) as client:
            with patch.object(llm,'OpenAI',return_value=client):
                result=llm._generate_response('Prompt',app_config={'llm_provider':'coarena','coarena_api_key':'simulated-key'},max_retries=0)
    assert result.startswith('Error:') and str(status) in result and len(calls)==1


def test_public_coarena_prepare_needs_no_openai_key_and_login_mode_stays_separate(monkeypatch):
    no_openai=Mock(side_effect=AssertionError('No OpenAI research key'));monkeypatch.setattr(ed,'research_key',no_openai)
    channel=ChannelProfile(channel_id='history',name='History',research_backend='public_coarena',script_provider='coarena')
    frozen=ed.prepare(channel,app_settings={'coarena_api_key':'simulated-key'})
    assert frozen.script_provider=='coarena' and frozen.script_model=='claude-fable-5'
    assert frozen.script_base_url=='https://coarena.ai/api/v1'
    no_openai.assert_not_called()
    with pytest.raises(RecoveryBlocked,match='API key Coarena'):ed.prepare(channel,app_settings={})
    with pytest.raises(RecoveryBlocked,match='exige selecionar'):public.require_backend('public_login','coarena')
    with pytest.raises(RecoveryBlocked,match='selecionar Coarena'):public.require_backend('public_coarena','openai_codex')


def test_coarena_public_research_keeps_receipts_and_does_not_use_openai(snapshot,report,tmp_path,monkeypatch):
    from app.services.autopilot.repository import Repository
    snapshot.channel.research_backend='public_coarena';snapshot.script_provider='coarena'
    monkeypatch.setitem(config.app,'coarena_api_key','simulated-key')
    monkeypatch.setattr(ed,'OpenAI',Mock(side_effect=AssertionError('No OpenAI Responses')))
    monkeypatch.setattr(public,'discover',lambda *a:discovered(report))
    monkeypatch.setattr(public,'read',lambda *a:pages(report))
    def text(prompt,frozen,*,output,**kwargs):
        assert frozen.script_provider=='coarena'
        if output==public.Queries:return public.Queries(queries=['Specific historical event'])
        if output==public.Selection:return public.Selection(candidate_ids=[1,2])
        return output.model_validate(report)
    monkeypatch.setattr(ed,'text',text)
    repo=Repository(tmp_path/'journal.sqlite3');repo.save_channel(snapshot.channel)
    task_id,_=repo.submit_editorial('Historical event',snapshot)
    result=public.run(repo,task_id,'search','Historical event',snapshot)
    assert result['research_backend']=='public_coarena' and set(result['retrieved'])=={'S1','S2'}
    ed.OpenAI.assert_not_called()
