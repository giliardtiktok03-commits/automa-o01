import json
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.models.schema import VideoParams
from app.services import material, codex_image, flow_browser, flow_automation, task
from app.services.ai33 import AI33Client, AI33Error
from app.services.ai33 import provider
from app.services.ai33.policy import SyntheticImagePolicyError


@pytest.mark.parametrize("entry", [
    lambda: material.generate_images_openai("test", 1),
    lambda: material._request_openai_image("https://example.test", {}),
    lambda: material.generate_images_codex("test", 1),
    lambda: codex_image.generate_image("test", None),
    lambda: flow_browser.generate("test", "unused", "profile", "unused"),
    lambda: flow_browser.start_test("profile", "unused"),
    lambda: flow_automation.generate(None, "test", "unused"),
])
def test_legacy_synthetic_image_entry_points_stop_before_network(entry):
    with patch("requests.sessions.Session.request") as network:
        with pytest.raises(SyntheticImagePolicyError, match="exclusivamente AI33"):
            entry()
        network.assert_not_called()


def test_ai33_configuration_is_frozen_without_key_in_project():
    params = VideoParams(video_subject="history")
    settings = {"ai33_api_key": "private-test-key", "ai33_image_model": "model-a",
                "ai33_image_resolution": "2K", "ai33_image_quality": "high", "ai33_image_max_credits": 986}
    provider.freeze(params, settings)
    provider.freeze(params, {**settings, "ai33_image_model": "model-b", "ai33_image_max_credits": 2000})
    assert params.ai33_model == "model-a" and params.ai33_max_credits == 986
    assert "private-test-key" not in params.model_dump_json()
    assert provider.parameters(params) == {"aspect_ratio": "9:16", "resolution": "2K", "quality": "high"}


def test_dynamic_model_prompt_limits_and_optional_resolution():
    client = AI33Client("test-key")
    catalog = [{"model_id": "limited", "max_generations": 4, "max_prompt_length": 2000,
                "requires_reference_images": False, "aspect_ratios": ["16:9"], "qualities": ["medium"]}]
    with patch.object(client, "models", return_value=catalog):
        client.validate("limited", {"aspect_ratio": "16:9", "quality": "medium"}, "test")
        with pytest.raises(AI33Error, match="2000"):
            client.validate("limited", {"aspect_ratio": "16:9"}, "x" * 2001)
        with pytest.raises(AI33Error, match="resolution"):
            client.validate("limited", {"aspect_ratio": "16:9", "resolution": "2K"}, "test")


SCRIPT = '''
import streamlit as st
from webui.ai33_settings import render
if 'settings' not in st.session_state:
    st.session_state.settings = {}
def save(section, key, value):
    st.session_state.settings[key] = value
render(dict(st.session_state.settings), save)
'''


def test_settings_mask_key_use_actual_catalog_and_quote_without_generation():
    catalog = [{"model_id": "model-no-resolution", "requires_reference_images": False,
                "supports_images": False, "max_generations": 4, "aspect_ratios": ["16:9"],
                "qualities": ["low", "high"], "default_quality": "high"}]
    with patch.object(AI33Client, "models", return_value=catalog) as models, \
         patch.object(AI33Client, "price", return_value=986) as price, \
         patch.object(AI33Client, "submit") as paid:
        app = AppTest.from_string(SCRIPT).run()
        assert not app.exception
        models.assert_not_called()
        app.text_input(key="ai33_api_key_input").set_value("private-test-key").run()
        app.button(key="ai33_load_models").click().run()
        assert not app.exception
        assert app.selectbox(key="ai33_image_model_select").value == "model-no-resolution"
        assert app.session_state.settings["ai33_image_resolution"] == ""
        assert app.session_state.settings["ai33_image_quality"] == "high"
        app.button(key="ai33_quote").click().run()
        assert not app.exception
        price.assert_called_once_with("model-no-resolution", {"aspect_ratio": "16:9", "quality": "high"})
        assert any("986" in message.value for message in app.success)
        assert app.text_input(key="ai33_api_key_input").proto.type == 1  # Streamlit PASSWORD enum
        paid.assert_not_called()
        app.text_input(key="ai33_api_key_input").set_value("other-key").run()
        assert "ai33_catalog" not in app.session_state


@pytest.mark.parametrize("source", ["openai_image", "codex_image"])
def test_legacy_source_rejected_before_consuming_pipeline(source):
    params = VideoParams(video_subject="history", video_source=source, subtitle_enabled=False)
    with patch.object(task, "generate_script") as script, patch.object(task, "generate_audio") as audio:
        result = task.start("legacy-disabled", params)
        assert result["failed_stage"] == "preflight"
        assert "unsupported video source" in result["error"]
        script.assert_not_called()
        audio.assert_not_called()


def test_chapter_migration_requires_original_fingerprint_and_unchanged_editorial(tmp_path):
    import hashlib
    from app.services import long_form
    from app.services import task_artifacts
    params = VideoParams(video_subject="history", video_source="mixed", mixed_image_provider="openai")
    saved = params.model_dump(mode="json")
    for key in ("mixed_use_ai33", "ai33_model", "ai33_resolution", "ai33_quality", "ai33_max_credits"):
        saved.pop(key)
    original = {k: v for k, v in saved.items() if k != "mixed_resume"}
    references = ["audio-digest", "", ""]
    fingerprint = hashlib.sha256(json.dumps({"params": original, "references": references}, sort_keys=True).encode()).hexdigest()
    manifest = {"version": 1, "fingerprint": fingerprint, "chapters": []}
    task_artifacts._write_json_atomic(tmp_path / "script.json", {"params": saved})
    task_artifacts._write_json_atomic(tmp_path / "chapters.json", manifest)
    params.mixed_image_provider = "ai33"
    params.ai33_model = "new-model"
    params.ai33_resolution = "2K"
    params.ai33_quality = ""
    params.ai33_max_credits = 986
    changed = params.model_copy(update={"video_subject": "changed"})
    assert not long_form._migrate_image_provider(changed, references, tmp_path, dict(manifest))
    assert not long_form._migrate_image_provider(params, ["other", "", ""], tmp_path, dict(manifest))
    assert long_form._migrate_image_provider(params, references, tmp_path, manifest)
    assert manifest["original_fingerprint"] == fingerprint
    assert manifest["fingerprint"] == long_form._fingerprint(params, references)
    assert (tmp_path / "ai33-migration-backup" / "script.json").is_file()


def test_main_ui_exposes_ai33_in_mixed_sources_without_flow():
    from pathlib import Path
    from app.config import config
    from app.services import version_checker
    root = Path(__file__).resolve().parents[2]
    with patch.dict(config.app, {"video_source": "mixed", "llm_provider": "openai"}, clear=True), \
         patch.dict(config.ui, {"language": "pt"}, clear=True), \
         patch.object(config, "try_save_config", return_value=True), \
         patch.object(version_checker, "get_available_update", return_value=None):
        app = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=30).run()
        assert not app.exception
        labels = [widget.label for widget in app.checkbox]
        assert "AI33.Pro · Imagens IA" in labels
        assert "Google Flow" not in labels
