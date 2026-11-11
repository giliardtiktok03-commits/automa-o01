"""Offline phase-2 tests: original packages, three concepts and export integrity."""
import hashlib
import json
import io
import zipfile
from uuid import uuid4
from unittest.mock import Mock
import pytest
from app.models.autopilot import ChannelProfile
from app.models.autopilot_editorial import EditorialSnapshot
from app.models.historical_director import Request, ThumbnailBrief
from app.models.channel_skill import ChannelSkillSnapshot
from app.services.historical_director import production as prod
from app.services.historical_director.library import SKILL_ID
from app.services.autopilot.recovery import RecoveryBlocked


def brief():
    return ThumbnailBrief(reference_adaptation='Use curiosity mechanisms without copying distinctive reference layouts.',
        concepts=[dict(name='Concept '+str(i),visual_promise='A truthful specific historical promise.',dominant_object='Document '+str(i),
            emotion='Curiosity',title_hook_alignment='The evidence answers the title and opening question.',historical_scene='Documented object in its proper context.',
            claim_ids=['C1'],layout='Distinct object placement and composition '+str(i),text='THE RECORD',palette_contrast='Dark background with clear warm highlights.',
            accuracy_constraints=['Use only the supported documented object.'],prompt_en='Original documentary archival visual in 16:9, with text-safe space and layout '+str(i),
            negative_prompt='No invented insignia, logos or inaccurate documents.') for i in range(3)])


@pytest.fixture
def snapshot():
    content='Historical evidence and original narration.'
    skill=ChannelSkillSnapshot(skill_id=SKILL_ID,name='Director',content=content,sha256=hashlib.sha256(content.encode()).hexdigest())
    return EditorialSnapshot(channel=ChannelProfile(channel_id='history',name='History',language='en-US',target_minutes=3,skill_ids=[SKILL_ID]),
        script_provider='openai',script_model='configured',skills=[skill])


@pytest.fixture
def result():
    return {'title':'Original title','script':' '.join('word'+str(i) for i in range(400)),
            'research':{'summary':'Summary of independently documented research.','claims':[{'id':'C1','statement':'Documented fact.',
                'evidence':[{'source_id':'S1','text':'A traceable source excerpt.'}]}],
                'sources':[{'id':'S1','title':'Archive','url':'https://archive.example/'}]},
            'metadata':{'description':'Intro\n\nReferences\nArchive — https://archive.example/','tags':['history'],'hashtags':['#history']},
            'thumbnail_concepts':brief().model_dump(),'thumbnail_reference_analysis':{'status':'no_images','images':[]},
            'quality_report':{'approved':True,'publish_allowed':False}}


def test_angle_context_is_frozen_without_mutating_skill(snapshot):
    frozen=prod.snapshot_for(snapshot,{'angle_id':'angle_01','core_question':'New angle'},Request(title='Original title'))
    assert frozen.skills[0].sha256!=snapshot.skills[0].sha256
    assert 'New angle' in frozen.skills[0].content
    assert 'New angle' not in snapshot.skills[0].content


def test_three_distinct_traceable_thumbnail_concepts(monkeypatch,snapshot,result):
    mock=Mock(return_value=brief());monkeypatch.setattr(prod.ed,'text',mock)
    output=prod.thumbnails(snapshot,{},result,{'status':'no_images'},Request(title='Original title'))
    assert len(output['concepts'])==3
    assert 'reference images/analysis' in mock.call_args.args[0]
    value=brief();value.concepts[2].claim_ids=['C9'];mock.return_value=value
    with pytest.raises(RecoveryBlocked,match='rastreável'):prod.thumbnails(snapshot,{},result,{},Request(title='Title'))
    value=brief();value.concepts[2].layout=value.concepts[0].layout;mock.return_value=value
    with pytest.raises(RecoveryBlocked,match='diferentes'):prod.thumbnails(snapshot,{},result,{},Request(title='Title'))


def test_reference_and_sibling_copying_block_quality(monkeypatch,snapshot,result):
    paid=Mock(return_value={'approved':True,'issues':[]});monkeypatch.setattr(prod.ed,'approved_review',paid)
    request=Request(title='Original title',reference_script=result['script'])
    with pytest.raises(RecoveryBlocked,match='referência'):prod.quality(snapshot,request,{},result,brief().model_dump(),[])
    request.reference_script='A completely different reference structure.'
    with pytest.raises(RecoveryBlocked,match='outro ângulo'):prod.quality(snapshot,request,{},result,brief().model_dump(),[result])
    paid.assert_not_called()
    checked=prod.quality(snapshot,request,{},result,brief().model_dump(),[])
    assert checked['approved'] and not checked['publish_allowed']
    assert checked['word_count']==400


def test_duration_gate_is_checked_before_another_model_call(monkeypatch,snapshot,result):
    paid=Mock();monkeypatch.setattr(prod.ed,'approved_review',paid)
    result['script']='Too short.'
    with pytest.raises(RecoveryBlocked,match='duração'):prod.quality(snapshot,Request(title='Title'),{},result,brief().model_dump(),[])
    paid.assert_not_called()


def test_all_artifacts_export_atomically_with_hashes_and_zip(monkeypatch,tmp_path,result):
    monkeypatch.setattr(prod.utils,'task_dir',lambda: str(tmp_path))
    task_id=str(uuid4());context={'language':'en-US','angle_version':1,'job_id':task_id}
    exported=prod.export(task_id,result,context)
    required={'research.md','script_en.txt','description_en.md','tags.txt','thumbnail_brief.md','thumbnail_prompts.json','sources.json','metadata.json','quality_report.json'}
    assert set(exported['files'])==required
    result.update(deliverables=exported,job_id=task_id)
    data=prod.archive(result)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert set(z.namelist())==required and z.testzip() is None
        assert json.loads(z.read('metadata.json'))['published'] is False
    path=prod.folder(task_id)/'script_en.txt';path.write_text('tampered')
    with pytest.raises(RecoveryBlocked,match='alterado'):prod.archive(result)


def test_originality_compares_words_without_punctuation():
    text=' '.join('word'+str(i) for i in range(30))
    assert prod.common_passage(text,text.upper().replace(' ',', '))
    assert not prod.common_passage('Only a short common sentence.',text)
