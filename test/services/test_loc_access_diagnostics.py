import json
from unittest.mock import patch
import pytest
from app.services.historical_archive.contracts import ArchiveSettings,ArchiveError
from app.services.historical_archive.network import Transport,loc_response_evidence
from app.services.historical_archive.diagnostics import DiagnosticRecorder
from test.services.test_loc_public_services import response,fake_clock


@pytest.mark.parametrize('headers,body,block',[
    ({'Content-Type':'text/html','Server':'cloudflare'},b'<title>Just a moment...</title>','anti_automation_challenge'),
    ({'cf-mitigated':'challenge'},b'private token','anti_automation_challenge'),
    ({'Content-Type':'text/html'},b'<script src="/cdn-cgi/challenge-platform/private-token"></script>','anti_automation_challenge'),
    ({'Content-Type':'text/html'},b'<title>Just a moment</title>','access_denied'),
    ({'Content-Type':'application/json'},b'{"error":"private token"}','access_denied'),
])
def test_categorize_403_without_copying_raw_data(headers,body,block):
    headers.update({'Set-Cookie':'private token','Authorization':'private token','Server-Secret':'private token'})
    evidence=loc_response_evidence(response(403,body,headers))
    assert evidence['block_kind']==block
    assert 'private token' not in json.dumps(evidence)


def test_inspection_bounded_and_never_json_parses_html():
    r=response(403,b'x'*20000,{'Content-Type':'text/html'})
    evidence=loc_response_evidence(r)
    assert evidence['inspected_body_bytes']==8192
    r.json.assert_not_called()


@pytest.mark.parametrize('code,expected',[(403,'anti_automation_challenge'),(429,None),(503,None)])
def test_safe_summary_and_cooldown_all_loc_services(tmp_path,monkeypatch,code,expected):
    recorder=DiagnosticRecorder(tmp_path/'reports',lambda:True)
    transport=Transport(tmp_path/'cache',ArchiveSettings(enabled=True),lambda:True,recorder.record)
    fake_clock(monkeypatch,transport)
    r=response(code,b'<title>Just a moment</title> secret-token',
               {'Content-Type':'text/html','Server':'cloudflare','Set-Cookie':'secret-token','Retry-After':'120'})
    with patch('app.services.historical_archive.network.requests.get',return_value=r) as http:
        with pytest.raises(ArchiveError):transport.get('loc_json','https://www.loc.gov/search/')
        with pytest.raises(ArchiveError):transport.get('loc_image','https://tile.loc.gov/image-services/iiif/x/info.json')
        http.assert_called_once()
        assert http.call_args.kwargs['headers']=={'User-Agent':ArchiveSettings().user_agent}
        assert http.call_args.kwargs['allow_redirects'] is False
    summary=recorder.read()['services']['loc_json']
    assert summary['http_statuses']==[code]
    assert summary['client_identification']=='project_default'
    assert summary['response_format']=='html'
    assert summary.get('block_kind')==expected
    assert 'secret-token' not in (tmp_path/'reports'/'diagnostic-report.json').read_text()
    assert 'Evidence:' in (tmp_path/'reports'/'diagnostic-report.md').read_text()
    if code==403:assert 'causa' not in summary['reason'] and 'não comprova' in summary['reason']
    if code==429:assert 'HTTP 429' in summary['reason']


def test_non_loc_unchanged_never_reads_block_body(tmp_path,monkeypatch):
    transport=Transport(tmp_path,ArchiveSettings(enabled=True),lambda:True)
    monkeypatch.setattr(transport,'pause',lambda *args:None)
    r=response(403,b'<title>Just a moment</title>',{'Content-Type':'text/html'})
    with patch('app.services.historical_archive.network.requests.get',return_value=r):
        with pytest.raises(ArchiveError,match='Provider HTTP 403'):
            transport.get('wikimedia','https://commons.wikimedia.org/w/api.php')
    r.iter_content.assert_not_called()
