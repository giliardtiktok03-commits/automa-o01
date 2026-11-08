import json
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
import requests
from streamlit.testing.v1 import AppTest

from app.models.schema import VideoParams
from app.services import runware_image as rw


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(rw.config, "app", {"runware_api_key": "private-test-key"})
    monkeypatch.setattr(rw.time, "sleep", lambda _: None)
    monkeypatch.setattr(rw, "download_png", lambda _: b"png-test-image")
    return VideoParams(video_subject="History", video_source="mixed", video_aspect="16:9")


def completed(task):
    return [{"taskUUID": task["taskUUID"], "taskType": "imageInference", "imageURL": "https://cdn.example.test/image.png", "cost": 0.001}]


def test_async_ack_poll_download_and_cache_without_second_paid_request(setup, tmp_path):
    def respond(task):
        return [] if task["taskType"] == "imageInference" else completed(task)
    with patch.object(rw.Client, "post", side_effect=respond) as post:
        callback = Mock()
        image, meta = rw.generate(setup, "Historic scene", tmp_path, before_submit=callback)
        again, same = rw.generate(setup, "Historic scene", tmp_path, existing_only=True)
    assert image == again and meta == same and image.read_bytes() == b"png-test-image"
    assert meta["cost_usd"] == 0.001
    callback.assert_called_once()
    tasks = [call.args[0] for call in post.call_args_list]
    assert [task["taskType"] for task in tasks] == ["imageInference", "getResponse"]
    paid = tasks[0]
    assert paid["model"] == "runware:100@1" and paid["steps"] == 4
    assert (paid["width"], paid["height"]) == (1024, 576)
    assert paid["numberResults"] == 1 and paid["includeCost"] is True
    assert paid["taskUUID"] == tasks[1]["taskUUID"]
    saved = (tmp_path / "runware-image.json").read_text()
    assert "private-test-key" not in saved and "https://" not in saved and "Historic scene" not in saved


def test_lost_ack_resumes_client_uuid_instead_of_resubmitting(setup, tmp_path):
    with patch.object(rw.Client, "post", side_effect=rw.RunwareError("Runware HTTP 503")) as post:
        with pytest.raises(rw.RunwareError, match="503"):
            rw.generate(setup, "Historic scene", tmp_path)
        assert post.call_count == 1
    old = json.loads((tmp_path / "runware-image.json").read_text())
    with patch.object(rw.Client, "post", side_effect=completed) as post:
        rw.generate(setup, "Historic scene", tmp_path, existing_only=True)
        assert post.call_args.args[0] == {"taskType": "getResponse", "taskUUID": old["task_id"]}


def test_deadline_is_pending_and_next_resume_does_not_order_again(setup, tmp_path, monkeypatch):
    monkeypatch.setattr(rw.time, "monotonic", Mock(side_effect=[0, 601]))
    with patch.object(rw.Client, "post", return_value=[]):
        with pytest.raises(rw.RunwarePending) as pending:
            rw.generate(setup, "Historic scene", tmp_path)
    state = json.loads((tmp_path / "runware-image.json").read_text())
    assert state["task_id"] == pending.value.task_id
    monkeypatch.setattr(rw.time, "monotonic", lambda: 0)
    with patch.object(rw.Client, "post", side_effect=completed) as post:
        rw.generate(setup, "Historic scene", tmp_path, existing_only=True)
        assert all(c.args[0]["taskType"] == "getResponse" for c in post.call_args_list)


def test_existing_only_missing_ledger_never_posts(setup, tmp_path):
    with patch.object(rw.Client, "post") as post, pytest.raises(rw.RunwareError, match="ausente"):
        rw.generate(setup, "Historic scene", tmp_path, existing_only=True)
    post.assert_not_called()


@pytest.mark.parametrize("bad", ["wrong_task", "error", "nsfw", "video", "multiple"])
def test_invalid_results_are_preserved_for_review_no_second_post(setup, tmp_path, bad):
    def respond(task):
        rows = completed(task)
        if bad == "wrong_task": rows[0]["taskUUID"] = str(uuid4())
        if bad == "error": rows[0]["status"] = "error"
        if bad == "nsfw": rows[0]["NSFWContent"] = True
        if bad == "video": rows[0]["taskType"] = "videoInference"
        if bad == "multiple": rows *= 2
        return rows
    with patch.object(rw.Client, "post", side_effect=respond) as post, pytest.raises(rw.RunwareError):
        rw.generate(setup, "Historic scene", tmp_path)
    assert post.call_count == 1 and (tmp_path / "runware-image.json").is_file()
    assert not (tmp_path / "image.png").exists()


def test_changed_spec_never_creates_another_paid_request(setup, tmp_path):
    with patch.object(rw.Client, "post", side_effect=completed):
        rw.generate(setup, "Historic scene", tmp_path)
    with patch.object(rw.Client, "post") as post, pytest.raises(rw.RunwareError, match="diferem"):
        rw.generate(setup, "Another scene", tmp_path)
    post.assert_not_called()


def test_transport_auth_array_no_retry_and_no_error_secret_leak():
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    response.json.return_value = {"data": []}
    with patch.object(rw.requests, "post", return_value=response) as post:
        rw.Client("secret-test-key").post({"taskType": "getResponse"})
        assert post.call_args.kwargs["json"] == [{"taskType": "getResponse"}]
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer secret-test-key"}
        assert post.call_args.kwargs["allow_redirects"] is False
    with patch.object(rw.requests, "post", side_effect=requests.Timeout("secret-test-key")) as post:
        with pytest.raises(rw.RunwareError) as error:
            rw.Client("secret-test-key").post({"taskType": "imageInference"})
        assert "secret-test-key" not in str(error.value)
        assert post.call_count == 1


def test_public_pricing_does_not_send_api_auth():
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    response.json.return_value = {"pricingOverview": "Reference", "pricingExamples": []}
    with patch.object(rw.requests, "get", return_value=response) as get:
        rw.Client.pricing(rw.DEFAULT_MODEL)
        assert "headers" not in get.call_args.kwargs
        assert get.call_args.args[0].startswith("https://content.runware.ai/")


def test_settings_masks_key_and_no_network_until_click():
    script = '''
import streamlit as st
from webui.runware_settings import render
if 'settings' not in st.session_state: st.session_state.settings = {}
def save(section, key, value): st.session_state.settings[key] = value
render(dict(st.session_state.settings), save)
'''
    with patch.object(rw.Client, "search", return_value=[{"air": rw.DEFAULT_MODEL, "name": "FLUX.1 Schnell"}]) as search, patch.object(rw, "generate") as paid:
        app = AppTest.from_string(script).run()
        assert not app.exception
        search.assert_not_called()
        app.text_input(key="runware_api_key_input").set_value("test-private-key").run()
        app.button(key="runware_models").click().run()
        assert not app.exception
        search.assert_called_once_with("FLUX")
        assert app.text_input(key="runware_api_key_input").proto.type == 1
        assert app.session_state.settings["runware_image_model"] == rw.DEFAULT_MODEL
        paid.assert_not_called()


def test_new_project_defaults_runware_enabled_ai33_disabled():
    params = VideoParams(video_subject="History")
    assert params.mixed_use_runware and not params.mixed_use_ai33
    assert params.mixed_image_provider == "runware"


def test_real_chapter_fingerprint_migrates_from_ai33_to_runware_preserving_editorial(tmp_path):
    from app.services import long_form, task_artifacts
    old = VideoParams(video_subject='History', video_source='mixed', mixed_image_provider='ai33',
                      mixed_use_runware=False, mixed_use_ai33=True, ai33_model='old-model')
    saved = old.model_dump(mode='json')
    # Before Runware existed these fields were absent from script.json.
    for name in ('mixed_use_runware', 'runware_model', 'runware_size', 'runware_steps'):
        saved.pop(name)
    references = ['audio-digest']
    fingerprint = long_form._fingerprint(old, references)
    manifest = {'version': 1, 'fingerprint': fingerprint, 'chapters': []}
    task_artifacts._write_json_atomic(tmp_path/'script.json', {'params': saved})
    task_artifacts._write_json_atomic(tmp_path/'chapters.json', manifest)
    new = old.model_copy(update={'mixed_image_provider': 'runware', 'mixed_use_runware': True,
                                 'mixed_use_ai33': False, 'runware_model': rw.DEFAULT_MODEL,
                                 'runware_size': 1024, 'runware_steps': 4})
    assert long_form._migrate_image_provider(new, references, tmp_path, manifest)
    assert manifest['continuation_image_provider'] == 'runware_image'
    changed = new.model_copy(update={'video_subject': 'Another subject'})
    assert not long_form._migrate_image_provider(changed, references, tmp_path, {'fingerprint': fingerprint})
