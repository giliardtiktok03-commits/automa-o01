from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import VideoParams
from app.services import channel_skills as library
from app.services import channel_skill_runtime as runtime
from app.services import llm, long_form, task, webui_task


CONTENT = b'''---
name: Test editorial profile
version: "1.0"
voice_profile: Measured documentary delivery
music_prompt: Quiet instrumental documentary underscore without vocals
---
Use a chronological structure. Separate verified facts from uncertainty.
'''


@pytest.fixture(autouse=True)
def local_library(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_root", lambda: tmp_path)
    return tmp_path


def test_import_revision_archive_and_saved_snapshot_survive(local_library):
    original = library.save("profile", CONTENT)
    params = VideoParams(video_subject="topic", skills_enabled=True, skill_ids=["profile"])
    runtime.freeze(params)
    replacement = library.save("profile", CONTENT.replace(b"1.0", b"2.0"), replace=True)
    assert replacement.sha256 != original.sha256
    assert (local_library / "profile/revisions" / (original.sha256 + ".md")).read_bytes() == CONTENT
    runtime.freeze(params)
    assert params.skill_snapshot[0].sha256 == original.sha256
    library.remove("profile")
    assert library.installed() == []
    runtime.freeze(params)
    assert params.skill_snapshot[0].content == original.content
    assert list((local_library / "_trash").iterdir())


@pytest.mark.parametrize("identifier", ["../outside", "/outside", "C:\\outside", "a/b", "a\\b", "_hidden", "a" * 49, "con", "com1"])
def test_ids_cannot_escape_library(identifier):
    with pytest.raises(library.ChannelSkillError):
        library.save(identifier, CONTENT)


@pytest.mark.parametrize("raw", [b"", b"\xff", b"\x00", b"x" * 24001,
                                b"---\nname: missing closing header", b"---\nname: [list]\n---\ntext",
                                b"---\nname: !!python/object/apply:os.system ['echo unsafe']\n---\ntext"])
def test_invalid_files_are_rejected_without_execution(raw):
    with patch("subprocess.run") as execute:
        with pytest.raises(library.ChannelSkillError):
            library.save("profile", raw)
        execute.assert_not_called()


def test_symlink_is_rejected(local_library, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_bytes(CONTENT)
    directory = local_library / "profile"
    directory.mkdir()
    (directory / "SKILL.md").symlink_to(outside)
    with pytest.raises(library.ChannelSkillError):
        library.load("profile")
    with pytest.raises(library.ChannelSkillError):
        library.save("profile", CONTENT, replace=True)


def test_inactive_mode_is_unchanged_and_never_reads_library():
    params = VideoParams(video_subject="topic", skill_ids=["missing"])
    with patch.object(library, "load") as load:
        runtime.freeze(params)
        assert params.skill_snapshot == []
        assert runtime.decorate("original prompt") == "original prompt"
        load.assert_not_called()


def test_priority_snapshot_integrity_and_context_isolation():
    first = library.save("primary", CONTENT)
    second = library.save("secondary", b"Complementary visual instructions")
    with runtime.scope([first, second]):
        decorated = runtime.decorate("Return only JSON")
        assert decorated.index('"skill_id": "primary"') < decorated.index('"skill_id": "secondary"')
        assert "requested output schema take priority" in decorated
        with ThreadPoolExecutor(1) as executor:
            assert executor.submit(runtime.decorate, "other job").result() == "other job"
    assert runtime.decorate("after job") == "after job"
    damaged = first.model_copy(update={"content": "changed"})
    with pytest.raises(library.ChannelSkillError, match="hash"):
        runtime.validate([damaged])
    with pytest.raises(library.ChannelSkillError):
        runtime.validate([first, first])


def test_central_llm_receives_skills_for_editorial_work_without_changing_provider():
    from openai.types.chat import ChatCompletion
    skill = library.save("profile", CONTENT)
    response = ChatCompletion(id="test", object="chat.completion", created=0, model="gpt-4.1-mini",
                              choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Narration"}}])
    settings = {"llm_provider": "openai", "openai_api_key": "private-test-key", "openai_model_name": "gpt-4.1-mini"}
    with patch.object(llm, "OpenAI") as create_client:
        client = create_client.return_value
        client.chat.completions.create.return_value = response
        with runtime.scope([skill]):
            assert llm._generate_response("Return a visual plan as JSON", app_config=settings) == "Narration"
        request = client.chat.completions.create.call_args.kwargs
        assert "chronological structure" in request["messages"][0]["content"]
        assert "Return a visual plan as JSON" in request["messages"][0]["content"]
        assert request["model"] == "gpt-4.1-mini"
        assert "private-test-key" not in request["messages"][0]["content"]


def test_music_guidance_does_not_override_user_prompt_or_voice():
    params = VideoParams(video_subject="topic", skills_enabled=True, skill_ids=["profile"], bgm_type="elevenlabs", voice_name="approved-voice")
    library.save("profile", CONTENT)
    runtime.freeze(params)
    assert task._get_video_music_prompt(params) == "Quiet instrumental documentary underscore without vocals"
    params.video_music_prompt = "Explicit musical choice"
    assert task._get_video_music_prompt(params) == "Explicit musical choice"
    assert params.voice_name == "approved-voice"


def test_queue_freezes_installed_content_before_later_edit():
    first = library.save("profile", CONTENT)
    params = VideoParams(video_subject="topic", skills_enabled=True, skill_ids=["profile"])
    with patch.dict(webui_task._active_submissions, {}, clear=True), patch.object(webui_task, "_enqueue_generation") as enqueue:
        webui_task.submit_generation("skills-queue-test", params)
        queued = enqueue.call_args.args[1]
        library.save("profile", CONTENT.replace(b"1.0", b"2.0"), replace=True)
        assert queued.skill_snapshot[0].sha256 == first.sha256
        assert params.skill_snapshot == []


def test_missing_skill_fails_before_consuming_pipeline():
    params = VideoParams(video_subject="topic", skills_enabled=True, skill_ids=["missing"])
    with patch.object(task, "generate_script") as script, patch.object(task, "generate_audio") as audio:
        result = task.start("missing-skill", params)
        assert result["failed_stage"] == "skills"
        script.assert_not_called()
        audio.assert_not_called()


def test_old_chapter_fingerprint_ignores_new_inactive_fields():
    params = VideoParams(video_subject="topic", video_source="mixed")
    raw = params.model_dump(mode="json")
    for key in ("skills_enabled", "skill_ids", "skill_snapshot", "mixed_resume", "mixed_grok_unlimited", "mixed_resume_subtitle_style", "subtitle_soft_shadow", "subtitle_max_lines",
                "runware_model", "runware_steps", "runware_size", "mixed_use_runware"):
        raw.pop(key)
    expected = hashlib.sha256(json.dumps({"params": raw, "references": []}, sort_keys=True).encode()).hexdigest()
    assert long_form._fingerprint(params, []) == expected


UI_SCRIPT = '''
import streamlit as st
from app.models.schema import VideoParams
from webui.channel_skills import render
params = VideoParams(video_subject='topic', voice_name='approved-voice')
def save(section,key,value): pass
def heading(number,label,color): st.markdown(f'{number:02d} · {label}')
render(st.container(), params, save, heading)
st.session_state['captured_params']=params.model_dump(mode='json')
'''


def test_ui_starts_in_standard_mode_and_captures_selection_without_switching_voice():
    library.save("profile", CONTENT)
    with patch.dict(config.ui, {}, clear=True):
        app = AppTest.from_string(UI_SCRIPT).run()
        assert not app.exception
        assert not app.checkbox(key="channel_skills_enabled").value
        app.checkbox(key="channel_skills_enabled").check().run()
        app.multiselect(key="channel_skill_ids").select("profile").run()
        assert not app.exception
        saved = app.session_state["captured_params"]
        assert saved["skill_snapshot"][0]["skill_id"] == "profile"
        assert saved["voice_name"] == "approved-voice"
        assert any("Measured documentary delivery" in item.value for item in app.info)


def test_ui_archiving_is_reversible_and_clears_selection():
    library.save("profile", CONTENT)
    with patch.dict(config.ui, {}, clear=True):
        app = AppTest.from_string(UI_SCRIPT).run()
        app.checkbox(key="channel_skills_enabled").check().run()
        app.multiselect(key="channel_skill_ids").select("profile").run()
        app.button(key="channel_skill_archive").click().run()
        assert not app.exception
        assert library.installed() == []
        assert app.session_state["captured_params"]["skill_snapshot"] == []
