"""Commons normalization keeps the shared rights policy unchanged."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from app.services.historical_archive.providers.wikimedia import WikimediaProvider
from app.services.historical_archive.rights import assess


def record(license_name='Public domain',usage='Public domain',restriction=''):
    return {'query':{'pages':{'2110142':{'pageid':2110142,
        'title':'File:World War II aircraft 1943.jpg','imageinfo':[{
            'mime':'image/jpeg','url':'https://upload.wikimedia.org/aircraft.jpg',
            'descriptionurl':'https://commons.wikimedia.org/wiki/File:Aircraft.jpg',
            'width':1920,'height':1080,'extmetadata':{
                'LicenseShortName':{'value':license_name},'UsageTerms':{'value':usage},
                'Restrictions':{'value':restriction}}}]}}}}


@pytest.mark.parametrize('short,usage',[
    ('Public domain','Public domain'),('Public domain','public DOMAIN'),
    ('Public  domain',' Public domain '),('Public domain','<span>Public domain</span>')])
def test_duplicate_commons_public_domain_fields_do_not_block_download(short,usage):
    transport=Mock();payload=record(short,usage);original=deepcopy(payload)
    transport.json.return_value=payload
    candidate=WikimediaProvider(transport).search('World War II aircraft 1943',['photograph'],5)[0]
    assert candidate.rights_statement.casefold()=='public domain'
    assert assess(candidate)[0]=='rights_cleared'
    assert candidate.metadata['record']==original['query']['pages']['2110142']
    assert payload==original
    params=transport.json.call_args.kwargs['params']
    assert params['gsrsearch']=='World War II aircraft 1943' and params['gsrnamespace']==6


@pytest.mark.parametrize('restriction,expected',[
    ('Non-commercial only','restricted'),('Permission required','restricted'),
    ('Public domain in the US only','needs_review'),('Public domain status not established','needs_review')])
def test_deduplication_never_erases_restrictions(restriction,expected):
    transport=Mock();transport.json.return_value=record(restriction=restriction)
    candidate=WikimediaProvider(transport).search('aircraft 1943',['photograph'],1)[0]
    assert restriction in candidate.rights_statement
    assert assess(candidate)[0]==expected


def test_ambiguous_or_absent_rights_stay_pending():
    transport=Mock();provider=WikimediaProvider(transport)
    for short,usage in [('',''),('Public domain status not established','Public domain status not established')]:
        transport.json.return_value=record(short,usage)
        assert assess(provider.search('aircraft',['photograph'],1)[0])[0]=='needs_review'
