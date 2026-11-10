import io
import json
import wave
import numpy as np
import pytest
from moviepy import AudioFileClip
from app.services import bgm


def track(name,frequency,rate=16000):
    stream=io.BytesIO()
    with wave.open(stream,'wb') as out:
        out.setparams((1,2,rate,0,'NONE','not compressed'))
        samples=np.sin(2*np.pi*frequency*np.arange(rate)/rate)*12000
        out.writeframes(samples.astype('<i2').tobytes())
    stream.seek(0);stream.name=name
    return stream


def test_playlist_concatenates_decoded_tracks_in_order_and_preserves_uploaded_sources(tmp_path,monkeypatch):
    monkeypatch.setattr(bgm,'uploaded_bgm_dir',lambda create=True:str(tmp_path))
    first,second=track('first.wav',440),track('second.wav',880,22050)
    filename=bgm.save_bgm_playlist([first,second])
    assert filename.startswith('playlist-')
    metadata=json.loads((tmp_path/(filename+'.json')).read_text())
    assert [item['original_name'] for item in metadata['tracks']]==['first.wav','second.wav']
    assert all((tmp_path/item['stored_name']).is_file() for item in metadata['tracks'])
    assert first.tell()==second.tell()==0
    with AudioFileClip(str(tmp_path/filename)) as audio:
        assert 1.9<audio.duration<2.2
        for start,expected in [(0.2,440),(1.2,880)]:
            rate=8000
            frames=audio.get_frame(start+np.arange(2000)/rate)
            signal=frames[:,0] if frames.ndim>1 else frames
            dominant=np.fft.rfftfreq(len(signal),1/rate)[np.argmax(np.abs(np.fft.rfft(signal)))]
            assert abs(dominant-expected)<8


def test_playlist_empty_or_too_many_files_rejected_before_saving(monkeypatch):
    from unittest.mock import Mock
    save=Mock();monkeypatch.setattr(bgm,'save_bgm_upload',save)
    for uploads in ([],[object()]*21):
        with pytest.raises(bgm.BgmUploadError):bgm.save_bgm_playlist(uploads)
    save.assert_not_called()


def test_playlist_ui_accepts_multiple_tracks_and_preserves_chosen_order_without_encoding():
    from unittest.mock import patch
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    first,second=track('a.wav',440),track('b.wav',880)
    first.size=len(first.getbuffer());second.size=len(second.getbuffer())
    script='''
import streamlit as st
from app.models.schema import VideoParams
from webui.bgm_playlist import render
params=VideoParams(video_subject='topic',bgm_type='custom')
files=render(params,True)
st.session_state['order']=[f.name for f in (files or [])]
'''
    with patch.object(st,'file_uploader',return_value=[first,second]) as upload, patch.object(bgm,'validate_bgm_upload') as validate, patch.object(bgm,'save_bgm_playlist') as encode:
        app=AppTest.from_string(script).run()
        assert not app.exception
        assert upload.call_args.kwargs['accept_multiple_files']
        assert upload.call_args.kwargs['max_upload_size']==200
        assert app.session_state['order']==['a.wav','b.wav']
        order=app.multiselect[0]
        order.unselect(0).run()
        app.multiselect[0].select(0).run()
        assert not app.exception
        assert app.session_state['order']==['b.wav','a.wav']
        assert validate.call_count==2  # Cached on rerun.
        encode.assert_not_called()
