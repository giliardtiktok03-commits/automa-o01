from pathlib import Path
from unittest.mock import patch
import pytest
from PIL import ImageFont
from streamlit.testing.v1 import AppTest
from app.models.schema import VideoParams
from app.services import subtitle_style, video


def test_profile_uses_real_extrabold_font_and_requested_values():
    font=ImageFont.truetype('resource/fonts/Montserrat-ExtraBold.ttf',60)
    assert 'ExtraBold' in ' '.join(font.getname())
    params=subtitle_style.apply(VideoParams(video_subject='History'),subtitle_style.DOCUMENTARY)
    assert params.font_size==60 and params.stroke_width==4
    assert params.text_fore_color=='#FFFFFF' and params.stroke_color=='#000000'
    assert params.subtitle_soft_shadow and params.subtitle_max_lines==2 and params.subtitle_position=='bottom'


def test_long_cue_splits_into_two_lines_without_losing_words_or_time():
    text=' '.join(['historical documentary']*12)
    wrap=lambda text:video.wrap_text(text,500,font='resource/fonts/Montserrat-ExtraBold.ttf',fontsize=60)[0]
    result=subtitle_style.limit_lines([((3,12),text)],2,wrap)
    assert len(result)>1 and all(len(value.split('\n'))<=2 for _,value in result)
    assert ' '.join(' '.join(value.split()) for _,value in result)==text
    assert result[0][0][0]==3 and result[-1][0][1]==12
    assert all(left[0][1]==right[0][0] for left,right in zip(result,result[1:]))


def test_override_changes_only_subtitle_fields():
    params=VideoParams(video_subject='History',grok_model='saved-image-model',custom_audio_file='saved.mp3')
    updated=subtitle_style.apply(params,{**subtitle_style.DOCUMENTARY,'grok_model':'wrong','custom_audio_file':'wrong'})
    assert updated.grok_model=='saved-image-model' and updated.custom_audio_file=='saved.mp3'


def test_preset_updates_real_streamlit_controls():
    from app.config import config
    from app.services import version_checker
    root=Path(__file__).resolve().parents[2]
    with patch.dict(config.app,{'video_source':'mixed','llm_provider':'openai'},clear=True),patch.dict(config.ui,{'language':'pt'},clear=True),patch.object(config,'try_save_config',return_value=True),patch.object(version_checker,'get_available_update',return_value=None):
        app=AppTest.from_file(str(root/'webui/Main.py'),default_timeout=30).run()
        assert not app.exception
        app.button(key='subtitle_documentary_preset').click().run()
        assert not app.exception
        assert app.slider(key='font_size_slider').value==60
        assert app.color_picker(key='font_color_picker').value=='#FFFFFF'
        assert app.color_picker(key='stroke_color_picker').value=='#000000'
        assert app.checkbox(key='subtitle_soft_shadow').value
        assert app.checkbox(key='subtitle_two_lines').value
        assert config.ui['font_name']=='Montserrat-ExtraBold.ttf'
        assert config.ui['stroke_width']==4


def test_real_video_renders_shadow_and_two_line_subtitles(tmp_path):
    import subprocess
    from app.utils import utils
    ffmpeg=utils.get_ffmpeg_binary()
    source=tmp_path/'source.mp4'
    audio=tmp_path/'audio.wav'
    subtitles=tmp_path/'subtitle.srt'
    output=tmp_path/'final.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','color=c=blue:s=640x360:r=24:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True)
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','sine=frequency=440:duration=1',str(audio)],check=True)
    subtitles.write_text('1\n00:00:00,000 --> 00:00:01,000\nA história revela segredos e acontecimentos que mudaram o mundo.\n',encoding='utf-8')
    params=subtitle_style.apply(VideoParams(video_subject='History',video_source='mixed',bgm_type='',n_threads=1),subtitle_style.DOCUMENTARY)
    with patch.object(video.VideoAspect,'to_resolution',return_value=(640,360)):
        assert video.generate_video(str(source),str(audio),str(subtitles),str(output),params)
    with video.VideoFileClip(str(output)) as clip:
        frame=clip.get_frame(.25)
        assert frame.shape[:2]==(360,640)
        assert ((frame[180:,:,0]>180)&(frame[180:,:,1]>180)&(frame[180:,:,2]>180)).any()
