import threading
import time

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm, webui_task


def test_queue_is_sequential_preserves_settings_and_continues_after_failure(monkeypatch):
    monkeypatch.setattr(webui_task, "_task_manager", InMemoryTaskManager(1, 10))
    monkeypatch.setattr(webui_task, "_active_submissions", {})
    monkeypatch.setattr(sm, "state", sm.MemoryState())
    monkeypatch.setattr(config, "app", config._SynchronizedConfig({"queue_test": 1}))
    monkeypatch.setattr(config, "save_config", lambda: None)
    first_started, release_first, third_done = threading.Event(), threading.Event(), threading.Event()
    seen, running = [], []

    def generate(task_id, params, **kwargs):
        assert not running
        running.append(task_id)
        seen.append((task_id, config.app["queue_test"], params.video_subject))
        try:
            if task_id == "first":
                first_started.set()
                assert release_first.wait(5)
                assert config.app["queue_test"] == 1
            if task_id == "second":
                raise RuntimeError("simulated failure")
            sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, videos=[task_id + ".mp4"])
            return {"videos": [task_id + ".mp4"]}
        finally:
            running.pop()
            if task_id == "third":
                third_done.set()

    monkeypatch.setattr(webui_task.tm, "start", generate)
    try:
        webui_task.submit_generation("first", VideoParams(video_subject="one"), capture_logs=False)
        assert first_started.wait(3)
        config.update_config_nonblocking(config.app, "queue_test", 2)
        second = VideoParams(video_subject="two")
        webui_task.submit_generation("second", second, capture_logs=False)
        second.video_subject = "changed after submission"
        config.update_config_nonblocking(config.app, "queue_test", 3)
        webui_task.submit_generation("third", VideoParams(video_subject="three"), capture_logs=False)
        assert [task_id for task_id, _ in webui_task.queue_snapshot()] == ["first", "second", "third"]
        assert sm.state.get_task("second")["generation_activity"]["phase"] == "queued"
        assert len(seen) == 1
    finally:
        release_first.set()
    assert third_done.wait(5)
    deadline = time.monotonic() + 3
    while webui_task.queue_snapshot() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == [("first", 1, "one"), ("second", 2, "two"), ("third", 3, "three")]
    assert config.app["queue_test"] == 3
    assert sm.state.get_task("second")["state"] == const.TASK_STATE_FAILED
    assert not webui_task.queue_snapshot()
