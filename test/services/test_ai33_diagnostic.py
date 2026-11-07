import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import diagnose_ai33 as diagnostic


KEY = "private-test-key"
TASK = "30258ee8-cfc0-4485-b1bc-2f9ba34bdc07"


def response(body=None, status=200, headers=None):
    mock = MagicMock()
    mock.__enter__.return_value = mock
    mock.status_code = status
    mock.headers = headers or {}
    mock.iter_content.return_value = [json.dumps(body).encode()]
    return mock


def project(tmp_path):
    directory = tmp_path / "project"
    scene = directory / "mixed/ai33-035"
    scene.mkdir(parents=True)
    (scene / "ai33-image.json").write_text(json.dumps({"task_id": TASK, "model_id": "bytedance-seedream-4.5", "status": "doing"}))
    return directory


@patch.object(diagnostic.time, "sleep")
@patch.object(diagnostic.requests, "get")
def test_diagnostic_only_reads_existing_tasks_and_reports_cache_without_exposing_secrets(get, sleep, tmp_path):
    processing = {"id": TASK, "status": "doing", "progress": 30, "created_at": "2026-11-07T20:03:32Z"}
    complete = {"id": TASK, "status": "done", "progress": 100,
                "metadata": {"prompt": "private prompt", "result_images": [{"imageUrl": "https://example.test/signed?secret=private"}]}}
    get.side_effect = [response({"success": True, "models": [{"model_id": "bytedance-seedream-4.5"}]}),
                       response({"success": True, "data": [{"id": TASK, "status": "doing", "metadata": {"prompt": "private prompt"}}]}),
                       response(processing, headers={"Age": "800", "X-Cache": "HIT " + KEY}), response(complete)]
    directory = project(tmp_path)
    before = (directory / "mixed/ai33-035/ai33-image.json").read_bytes()
    report = diagnostic.diagnose(directory, KEY)
    sample = report["tarefas"][0]["consultas"]
    assert [s["status"] for s in sample] == ["doing", "done"]
    assert sample[0]["cabecalhos"]["Age"] == "800"
    assert sample[1]["imagens_disponiveis"] == 1
    assert "estimativa_do_catalogo_segundos" not in report["tarefas"][0]
    for secret in (KEY, "private prompt", "example.test", "secret=private"):
        assert secret not in json.dumps(report)
    assert get.call_count == 4
    assert all(call.args[0].startswith("https://api.ai33.pro/") for call in get.call_args_list)
    assert all(not call.kwargs["allow_redirects"] for call in get.call_args_list)
    assert get.call_args_list[-1].kwargs["headers"]["Cache-Control"] == "no-cache"
    assert before == (directory / "mixed/ai33-035/ai33-image.json").read_bytes()


@patch.object(diagnostic.time, "sleep")
@patch.object(diagnostic.requests, "get")
def test_rate_limit_stops_diagnostic_without_retry(get, sleep, tmp_path):
    get.side_effect = [response({"success": True, "models": []}), response({"success": True, "data": []}), response(status=429, headers={"Retry-After": "60"})]
    report = diagnostic.diagnose(project(tmp_path), KEY)
    assert "interrompido" in report
    assert get.call_count == 3
    assert len(report["tarefas"][0]["consultas"]) == 1


@patch.object(diagnostic.requests, "get")
def test_wrong_task_identity_and_oversize_body_are_not_trusted(get):
    get.return_value = response({"id": "other", "status": "done"})
    assert "erro" in diagnostic.task_sample(TASK, KEY)
    big = response({})
    big.iter_content.return_value = [b"x" * (2 * 1024 * 1024 + 1)]
    get.return_value = big
    assert "erro" in diagnostic.probe("/v1i/models", KEY)[0]
    get.reset_mock()
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.task_sample("../another-path", KEY)
    get.assert_not_called()


def test_main_uses_saved_local_key_and_writes_filtered_report(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "storage/tasks" / "5ea95e86-2852-4ecc-9fde-5beabd62fcdd"
    (directory / "mixed/ai33-036").mkdir(parents=True)
    (directory / "mixed/ai33-036/ai33-image.json").write_text(json.dumps({"task_id": TASK}))
    (tmp_path / "config.toml").write_text('[app]\nai33_api_key = "' + KEY + '"\n')
    monkeypatch.setattr(diagnostic, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["diagnose_ai33.py", directory.name])
    with patch.object(diagnostic, "diagnose", return_value={"somente_consulta": True}) as query:
        diagnostic.main()
        assert query.call_args.args == (directory, KEY)
    assert KEY not in capsys.readouterr().out
    assert len(list((tmp_path / "storage/diagnostics").glob("ai33-*.json"))) == 1
