"""Offline phase-1 tests: real validation, image decoding and reviewed eligibility."""
import io
from unittest.mock import Mock
import pytest
from PIL import Image
from app.models.historical_director import Request, Analysis, EligibilityReview, Weights
from app.models.autopilot import ChannelProfile
from app.models.autopilot_editorial import EditorialSnapshot
from app.services.historical_director import analysis, images, library
from app.services import channel_skills
from app.services.autopilot.recovery import RecoveryBlocked


def picture(color='red',fmt='PNG'):
    stream=io.BytesIO();Image.new('RGB',(160,90),color).save(stream,format=fmt);return stream.getvalue()


def proposal():
    questions=['Who controlled the deception plan?', 'Which documents shaped the final outcome?',
               'How did naval constraints affect logistics?', 'What did the postwar testimony establish?',
               'Why did technical alternatives prove costly?']
    return Analysis(theme='A synthetic documentary test theme.',reference_angle='Reference perspective for testing.',
        reference_structure=['Opening question','Development','Payoff'],central_channel_angle='Evidence first',
        alternatives=[dict(angle_id=f'angle_0{i+1}',name=f'Angle {i+1}',title_en=f'English documentary perspective number {i+1}',
            title_pt=f'Perspectiva documental número {i+1}',core_question=q,point_of_view='A documented original perspective.',
            conflict='Objective versus documented constraints.',emotional_trigger='Curiosity',originality_delta='A substantively different development and payoff.',
            story_framework='A',hook_proposal='A documented question opens this story.',payoff_promise='Answer based on the original source record.',
            thumbnail_hook=f'A distinct documentary visual object {i+1}.',source_feasibility='Supplied source excerpts support this angle.',
            supporting_claim_ids=['C1'],gates={'on_topic':True,'credible':True,'differentiated':True},
            scores={k:90-i for k in Weights().model_dump()},score_reason='The question and evidence support this editorial choice.') for i,q in enumerate(questions)])


def decisions(duplicate=False):
    from itertools import combinations
    ids=[f'angle_0{i}' for i in range(1,6)]
    return EligibilityReview(decisions=[{'angle_id':a,'eligible':True,'reasons':['Supported by this synthetic record.']} for a in ids],
        pairs=[{'left':a,'right':b,'differentiated':not(duplicate and (a,b)==('angle_01','angle_02')),
                'reason':'Different information and perspective are evaluated.'} for a,b in combinations(ids,2)])


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(images,'root',lambda:tmp_path/'images')
    (tmp_path/'images').mkdir()
    monkeypatch.setattr(channel_skills,'_root',lambda:tmp_path/'skills')
    (tmp_path/'skills').mkdir()
    return tmp_path


def test_optional_controls_and_explicit_multiple():
    assert Request(title='Title').automatic_top_n==1
    for data in [dict(title='Title',skill_enabled=False),dict(title='Title',publish_mode='public'),dict(title='Title',automatic_top_n=5)]:
        with pytest.raises(ValueError):Request(**data)
    assert Request(title='Title',automatic_top_n=5,automatic_multiple=True).automatic_top_n==5
    with pytest.raises(ValueError):Weights(curiosity=10)


@pytest.mark.parametrize('count',[0,1,2,3])
def test_zero_to_three_reference_images_work(isolated,count):
    refs=images.upload([picture(c) for c in ['red','green','blue'][:count]])
    assert len(refs)==count
    for ref in refs:
        with Image.open(io.BytesIO(images.read(ref))) as image:assert not image.getexif()


def test_rejects_four_duplicate_corrupt_oversize_and_animated_images(isolated):
    with pytest.raises(ValueError,match='máximo 3'):images.upload([picture()]*4)
    with pytest.raises(ValueError,match='repetidas'):images.upload([picture()]*2)
    with pytest.raises(ValueError):images.upload([b'bad'])
    with pytest.raises(ValueError,match='MB'):images.store(b'x'*(1024*1024+1),max_mb=1)
    with pytest.raises(ValueError):images.store(picture(fmt='GIF'))
    ref=images.upload([picture()])[0];images.location(ref.image_id).write_bytes(b'changed')
    with pytest.raises(ValueError,match='alterada'):images.read(ref)


def test_installer_preserves_edits_and_archiving(isolated):
    library.install();skill=channel_skills.load(library.SKILL_ID)
    assert skill.name=='Historical Documentary Director'
    channel_skills.save(library.SKILL_ID,b'User edited instructions',replace=True)
    library.install();assert channel_skills.load(library.SKILL_ID).content=='User edited instructions'
    channel_skills.remove(library.SKILL_ID);library.install()
    assert not channel_skills.installed()


def test_visual_off_never_reads_or_calls_provider(monkeypatch,isolated):
    refs=images.upload([picture()])
    paid=Mock();monkeypatch.setattr(analysis.ed,'OpenAI',paid)
    monkeypatch.setattr(images,'read',Mock(side_effect=AssertionError('must not read')))
    assert analysis.visual(Request(title='Title',thumbnails=refs))['status']=='disabled'
    assert analysis.visual(Request(title='Title',thumbnail_reference_enabled=True))['status']=='no_images'
    paid.assert_not_called()


def test_review_excludes_semantically_close_angle_and_ranks_locally(monkeypatch):
    request=Request(title='Title')
    snap=EditorialSnapshot(channel=ChannelProfile(channel_id='a',name='A'),script_provider='openai',script_model='configured')
    monkeypatch.setattr(analysis.ed,'text',lambda *a,**kw:decisions(duplicate=True))
    result=analysis.eligible(request,snap,{'claims':[]},proposal())
    assert result['recommended_ids'][0]=='angle_01'
    assert 'angle_02' not in result['recommended_ids']
    assert result['analysis']['alternatives'][0]['editorial_score']==90
    assert not result['analysis']['alternatives'][1]['eligible']


def test_unknown_claim_and_incomplete_pair_review_block(monkeypatch):
    snap=EditorialSnapshot(channel=ChannelProfile(channel_id='a',name='A'),script_provider='openai',script_model='configured')
    monkeypatch.setattr(analysis.ed,'text',lambda *a,**kw:proposal())
    with pytest.raises(RecoveryBlocked,match='inexistentes'):
        analysis.propose(Request(title='Title'),snap,{'claims':[]},{'status':'no_images'})
    response=decisions();response.pairs[0]=response.pairs[1]
    monkeypatch.setattr(analysis.ed,'text',lambda *a,**kw:response)
    with pytest.raises(RecoveryBlocked,match='incompleta'):
        analysis.eligible(Request(title='Title'),snap,{'claims':[]},proposal())


@pytest.mark.parametrize('count',[1,2,3])
def test_visual_enabled_sends_exact_safe_images_and_records_their_ids(isolated,monkeypatch,count):
    import json
    from types import SimpleNamespace
    refs=images.upload([picture(c) for c in ['red','green','blue'][:count]])
    value={'images':[dict(image_id=r.image_id,visual_hook='A contrasting documented object raises a question.',
        composition='Dominant object with empty text space.',palette_lighting='Warm foreground on a dark background.',
        visible_text='',mobile_readability='Readable silhouette, text not legible.',reusable_mechanisms=['Object contrast'],
        do_not_copy=['Brand and distinctive typography'],limitations=['Identity and performance cannot be inferred.']) for r in refs],
        'shared_curiosity':'A documentary object implies an unanswered question.','incompatibilities':[]}
    client=Mock();client.responses.create.return_value=SimpleNamespace(status='completed',output_text=json.dumps(value))
    sdk=Mock();sdk.return_value.__enter__=Mock(return_value=client);sdk.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr(analysis.ed,'OpenAI',sdk);monkeypatch.setattr(analysis.ed,'research_key',lambda:'fake-key')
    result=analysis.visual(Request(title='Original title',thumbnail_reference_enabled=True,thumbnails=refs))
    assert result['status']=='analyzed' and len(result['images'])==count
    content=client.responses.create.call_args.kwargs['input'][0]['content']
    assert len([c for c in content if c['type']=='input_image'])==count
    assert client.responses.create.call_args.kwargs['store'] is False
    assert sdk.call_args.kwargs['max_retries']==0
