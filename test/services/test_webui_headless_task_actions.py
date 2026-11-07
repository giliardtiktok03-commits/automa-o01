import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config

# webui/Main.py 在导入 app.services.material 时会连带导入 moviepy，而 moviepy 在
# 导入期就要解析 FFmpeg 可执行文件（依赖 sys.platform 选择平台二进制），numpy 也
# 会按 sys.platform 决定是否调用 os.uname()。这些解析必须先于下面的 fixture 完成，
# 否则在 Windows 上模拟无桌面服务器时会去找 Linux 版 FFmpeg 或直接抛 AttributeError。
from app.services import material as _material  # noqa: F401
from app.services import state as sm
from app.utils import utils

ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


@pytest.fixture
def headless_task_app(tmp_path, monkeypatch):
    # 使用独立任务目录避免读取或修改开发者的真实生成记录。测试文件只需要被
    # Streamlit 注册为媒体资源，不参与视频解码，因此无需在单元测试中调用
    # FFmpeg 生成素材，能够稳定覆盖无桌面服务器的 UI 分支。
    tasks_dir = tmp_path / "storage" / "tasks"
    task_dir = tasks_dir / "headless-test"
    task_dir.mkdir(parents=True)
    video_file = task_dir / "final-1.mp4"
    video_file.write_bytes(b"test video payload")

    monkeypatch.setattr(utils, "task_dir", lambda: str(tasks_dir))
    monkeypatch.setattr(sm.state, "get_all_tasks", lambda *_args, **_kwargs: ([], 0))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    # AppTest 会多次重新执行页面脚本；配置保存必须在整个测试生命周期内保持
    # 隔离，防止控件初始化意外写入开发者的 config.toml。
    with patch.object(config, "try_save_config", return_value=True):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        yield app, video_file


def _button_by_key_prefix(app, key_prefix):
    return next(button for button in app.button if str(button.key).startswith(key_prefix))


def test_headless_play_renders_and_closes_browser_preview(headless_task_app):
    app, video_file = headless_task_app

    _button_by_key_prefix(app, "play_task_all_headless-test").click()
    app.run()

    assert not app.exception
    assert app.session_state["task_preview_video_file"] == str(video_file.resolve())
    assert len(app.get("video")) == 1

    _button_by_key_prefix(app, "close_task_video_preview").click()
    app.run()

    assert "task_preview_video_file" not in app.session_state
    assert len(app.get("video")) == 0


def test_headless_open_folder_shows_host_mapped_path(headless_task_app):
    app, _ = headless_task_app

    _button_by_key_prefix(app, "open_task_all_headless-test").click()
    app.run()

    assert not app.exception
    # _open_task_path() 用 os.path.relpath() 生成相对部分，因此分隔符跟随运行
    # 测试的平台。headless 分支是靠 monkeypatch sys.platform 进入的，在 Windows
    # 上提示文本仍会带反斜杠，断言不能写死 POSIX 分隔符。
    expected_folder = os.path.join("tasks", "headless-test")
    assert any(
        f"./storage/{expected_folder}" in toast.value for toast in app.get("toast")
    )


def test_chapter_mode_exposes_duration_and_resume_controls(headless_task_app):
    app, _ = headless_task_app
    app.checkbox(key="long_form_enabled").check()
    app.run()
    assert not app.exception
    assert app.slider(key="long_form_target_minutes").max == 30
    assert app.slider(key="long_form_chapter_minutes").max == 5
    assert app.text_input(key="long_form_resume_task_id").value == ""


def test_narration_picker_allows_500_mb(headless_task_app, monkeypatch):
    app, _ = headless_task_app
    monkeypatch.setitem(config.ui, "voice_mode", config.ui.get("voice_mode"))
    language = app.session_state["ui_language"]
    app.session_state[f"voice_mode_control_{language}"] = "upload"
    app.run()
    assert not app.exception
    uploaders = app.get("file_uploader")
    assert any(element.proto.max_upload_size_mb == 500 for element in uploaders)


def test_mixed_mode_shows_budget_and_forces_narrative_order(headless_task_app, monkeypatch):
    app, _ = headless_task_app
    monkeypatch.setitem(config.app, "video_source", config.app.get("video_source", "pexels"))
    monkeypatch.setitem(config.app, "match_materials_to_script", config.app.get("match_materials_to_script", False))
    language = app.session_state["ui_language"]
    app.session_state[f"video_source_select_{language}"] = "mixed"
    app.run()
    assert not app.exception
    assert app.number_input(key="mixed_max_images").value == 12
    assert app.slider(key="mixed_scene_duration").value == 10
    assert app.checkbox(key="mixed_variable_pacing").value is True
    assert app.checkbox(key="match_materials_to_script").value is True
    assert app.checkbox(key="match_materials_to_script").disabled


def test_subtitle_settings_offer_whisper_and_a_small_model(headless_task_app, monkeypatch):
    app, _ = headless_task_app
    monkeypatch.setitem(config.app, "subtitle_provider", config.app.get("subtitle_provider", "edge"))
    monkeypatch.setitem(config.whisper, "model_size", config.whisper.get("model_size", "large-v3"))
    language = app.session_state["ui_language"]
    app.selectbox(key=f"subtitle_provider_select_{language}").set_value("whisper")
    app.run()
    assert not app.exception
    app.selectbox(key=f"whisper_model_select_{language}").set_value("small")
    app.run()
    assert not app.exception
    assert config.app["subtitle_provider"] == "whisper"
    assert config.whisper["model_size"] == "small"


def test_stages_have_distinct_numbered_colors(headless_task_app):
    app, _ = headless_task_app
    headings = " ".join(item.value for item in app.markdown)
    for number, color in [("01", "#6d28d9"), ("02", "#0369a1"), ("03", "#b45309"), ("04", "#047857")]:
        assert number in headings and color in headings
    assert not app.button(key="generate_video_button").disabled


def test_flow_profile_controls_open_manual_login_without_password_field(headless_task_app, monkeypatch):
    from app.services import flow_browser
    from unittest.mock import Mock
    app, _ = headless_task_app
    for key in ('mixed_image_provider','flow_profile','flow_project_url'):
        monkeypatch.setitem(config.ui, key, config.ui.get(key, ''))
    language = app.session_state['ui_language']
    app.session_state[f'video_source_select_{language}'] = 'mixed'
    app.run()
    assert not app.exception
    app.text_input(key='flow_profile').set_value(' giliard ')
    url = 'https://flow.google.com/project/39a3cd68-17c5-4695-8c99-52ea21b38e66'
    app.text_input(key='flow_project_url').set_value(url)
    connect = Mock()
    monkeypatch.setattr(flow_browser, 'connect', connect)
    app.button(key='flow_connect').click().run()
    assert not app.exception
    connect.assert_called_once_with('giliard', url)
    assert config.ui['flow_profile'] == 'giliard'


def test_mixed_sources_all_start_checked(headless_task_app, monkeypatch):
    app, _ = headless_task_app
    for source in ('pexels','pixabay','coverr','openai','flow'):
        monkeypatch.setitem(config.ui,'mixed_use_'+source,True)
    language=app.session_state['ui_language']
    app.session_state[f'video_source_select_{language}']='mixed'
    app.run()
    assert not app.exception
    for source in ('pexels','pixabay','coverr','openai','flow'):
        assert app.checkbox(key='mixed_use_'+source).value is True
    app.checkbox(key='mixed_use_flow').uncheck().run()
    assert not app.exception
    assert not app.checkbox(key='mixed_use_flow').value
    assert all(item.key!='flow_connect' for item in app.button)


def test_saved_project_check_uses_original_id_and_total_budget(headless_task_app, monkeypatch):
    from unittest.mock import Mock
    from app.models.schema import VideoParams
    from app.services import mixed_resume
    app, _ = headless_task_app
    task_id='5c8b2e2a-3360-449a-a84d-297f6ab90bcf'
    project={'task_id':task_id,'params':VideoParams(video_subject='Saved project', mixed_resume=True),
             'ready':21,'total':60,'started':12}
    load=Mock(return_value=project)
    monkeypatch.setattr(mixed_resume,'load',load)
    app.text_input(key='mixed_resume_id').set_value(task_id)
    app.number_input(key='mixed_resume_limit').set_value(24)
    app.button(key='mixed_resume_check').click().run()
    assert not app.exception
    load.assert_called_once_with(task_id,24)
    assert any('21/60' in item.value and '12' in item.value and '24' in item.value for item in app.info)
