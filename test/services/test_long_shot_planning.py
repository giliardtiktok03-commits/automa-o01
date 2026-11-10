import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from app.services import mixed_materials as mixed


def choices(units):
    return [dict(id=u['id'],source='stock',context='current',period='today',location='unknown',search_query=f'visual {u["id"]}',image_prompt=f'Unique visual {u["id"]}',reason='Contextual detail',stock_safe=True) for u in units]


def test_twenty_minute_five_second_shots_cover_every_frame_without_slowing_cuts():
    units=[dict(id=1,text='Narration',start_frame=0,end_frame=1200*30)]
    shots=mixed.shot_timeline(units,1200,0,5)
    assert len(shots)==244
    assert shots[0]['start_frame']==0 and shots[-1]['end_frame']==36000
    assert all(a['end_frame']==b['start_frame'] for a,b in zip(shots,shots[1:]))
    assert [s['end_frame']-s['start_frame'] for s in shots[:10]]==[90]*10
    assert all(s['end_frame']-s['start_frame']==150 for s in shots[10:])


def test_large_plan_batched_exact_global_order_and_reuses_completed_batches(tmp_path,monkeypatch):
    units=[dict(id=i,text=f'Unit {i}',start_frame=(i-1)*150,end_frame=i*150) for i in range(1,245)]
    calls=[]
    fail=[True]
    def model(prompt):
        data=json.loads(prompt.split('INPUT JSON:\n')[1])
        batch=data['units'];calls.append([u['id'] for u in batch])
        if len(calls)==3 and fail[0]:raise mixed.MixedError('temporary failure')
        return json.dumps(choices(batch))
    monkeypatch.setattr(mixed.llm,'_generate_response',lambda **kw:model(kw['prompt']))
    checkpoint=tmp_path/'plan.json'
    with pytest.raises(mixed.MixedError):mixed._plan(units,'Narration',checkpoint)
    assert len(json.loads(checkpoint.read_text())['scenes'])==60
    fail[0]=False
    planned=mixed._plan(units,'Narration',checkpoint)
    assert [s['id'] for s in planned]==list(range(1,245))
    assert max(map(len,calls))<=mixed.PLAN_BATCH_SIZE
    assert calls[3][0]==61  # Earlier successful calls were not repeated.
    count=len(calls)
    assert mixed._plan(units,'Narration',checkpoint)==planned
    assert len(calls)==count


def test_corrupt_plan_cannot_reorder_units_without_new_model_calls(tmp_path,monkeypatch):
    units=[dict(id=1,text='Text',start_frame=0,end_frame=150)]
    monkeypatch.setattr(mixed.llm,'_generate_response',lambda **kw:json.dumps(choices(units)))
    checkpoint=tmp_path/'plan.json';mixed._plan(units,'Text',checkpoint)
    saved=json.loads(checkpoint.read_text());saved['scenes'][0]['end_frame']=999
    checkpoint.write_text(json.dumps(saved))
    call=Mock();monkeypatch.setattr(mixed.llm,'_generate_response',call)
    with pytest.raises(mixed.MixedError,match='parcial inválido'):mixed._plan(units,'Text',checkpoint)
    call.assert_not_called()
