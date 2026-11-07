"""Read-only diagnosis of existing image tasks. Never submits paid requests."""

import argparse
from datetime import datetime
import json
import math
import os
import platform
from pathlib import Path
import re
import time
import tomllib
from uuid import UUID

import requests

BASE = "https://api.ai33.pro"
ROOT = Path(__file__).resolve().parents[1]


class DiagnosticError(ValueError):
    pass


def safe_text(value, secret=""):
    text = str(value or "")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\b(?:sk|rk|sess)[_-][A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    text = re.sub(r"https?://\S+", "[URL]", text)
    return "".join(c for c in text if c.isprintable())[:320]


def probe(path, key, *, no_cache=False):
    # Fixed API host, GET only, no redirects and no response-body logging.
    headers = {"xi-api-key": key}
    if no_cache:
        headers["Cache-Control"] = "no-cache"
    started = time.perf_counter()
    sample = {"consultado_em": datetime.now().astimezone().isoformat(),
              "modo": "pedir_revalidacao_cache" if no_cache else "consulta_normal"}
    try:
        with requests.get(BASE + path, headers=headers, timeout=(15, 30),
                          allow_redirects=False, stream=True) as response:
            sample["http_status"] = response.status_code
            sample["cabecalhos"] = {name: safe_text(response.headers[name], key)
                                     for name in ("Date", "Age", "Cache-Control", "CF-Cache-Status", "X-Cache", "Retry-After", "Server")
                                     if name in response.headers}
            if response.status_code != 200:
                return sample, None
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024:
                    sample["erro"] = "Resposta acima do limite de diagnóstico"
                    return sample, None
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                sample["erro"] = "Resposta não JSON"
                return sample, None
            if not isinstance(payload, dict):
                sample["erro"] = "Estrutura de resposta inesperada"
                return sample, None
            return sample, payload
    except requests.RequestException as exc:
        sample["erro"] = type(exc).__name__  # Never copy an exception with auth/body.
        return sample, None
    finally:
        sample["segundos_da_consulta"] = round(time.perf_counter() - started, 3)


def task_sample(task_id, key, *, no_cache=False):
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
        raise DiagnosticError("ID remoto inválido; nenhum pedido foi enviado")
    sample, body = probe("/v1/task/" + task_id, key, no_cache=no_cache)
    if body is None:
        return sample
    if body.get("id") != task_id:
        sample["erro"] = "A resposta não corresponde ao ID consultado"
        return sample
    sample["status"] = body.get("status") if body.get("status") in {"doing", "done", "error"} else "inesperado"
    progress = body.get("progress")
    if isinstance(progress, (int, float)) and not isinstance(progress, bool) and math.isfinite(progress):
        sample["progress"] = progress
    # These optional dates are recorded only if actually present and parseable.
    sample["datas_retornadas"] = {}
    for name in ("created_at", "started_at", "updated_at", "completed_at", "finished_at"):
        value = body.get(name)
        if isinstance(value, str) and len(value) <= 80:
            try:
                sample["datas_retornadas"][name] = datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
            except ValueError:
                pass
    metadata = body.get("metadata")
    images = metadata.get("result_images") if isinstance(metadata, dict) else None
    sample["imagens_disponiveis"] = len(images) if isinstance(images, list) else 0
    if sample["status"] == "error":
        sample["erro_do_provedor"] = safe_text(body.get("error_message"), key)
    return sample


def local_tasks(directory):
    files = sorted(directory.glob("mixed/ai33-*/ai33-image.json"), key=lambda p: p.stat().st_mtime)
    result = []
    for file in files[-3:]:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
            continue
        result.append({"cena": file.parent.name, "task_id": task_id,
                       "modelo": safe_text(data.get("model_id")),
                       "estado_local": data.get("status") if data.get("status") in {"doing", "done", "submitted", "saved", "error"} else "desconhecido",
                       "registro_local_atualizado_em": datetime.fromtimestamp(file.stat().st_mtime).astimezone().isoformat()})
    return result


def diagnose(directory, key):
    tasks = local_tasks(directory)
    if not tasks:
        raise DiagnosticError("Nenhuma tarefa AI33 com ID confirmado neste projeto")
    report = {"projeto": directory.name, "gerado_em": datetime.now().astimezone().isoformat(),
              "somente_consulta": True, "tarefas": tasks,
              "ambiente": {"python": platform.python_version(), "requests": requests.__version__,
                           "proxy_no_ambiente": any(os.environ.get(name) for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")),
                           "certificado_customizado_no_ambiente": bool(os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE"))}}
    sample, catalog = probe("/v1i/models", key)
    report["consulta_catalogo"] = sample
    models = catalog.get("models", []) if catalog and catalog.get("success") is True else []
    if not isinstance(models, list):
        models = []
        sample["erro"] = "Catálogo com formato inesperado"
        catalog = None
    for task in tasks:
        entry = next((m for m in models if isinstance(m, dict) and m.get("model_id") == task["modelo"]), None)
        if catalog and catalog.get("success") is True:
            task["modelo_no_catalogo"] = entry is not None
        if entry and isinstance(entry.get("eta_seconds"), (int, float)) and not isinstance(entry["eta_seconds"], bool) and math.isfinite(entry["eta_seconds"]):
            task["estimativa_do_catalogo_segundos"] = entry["eta_seconds"]
    if sample.get("http_status") in (401, 403, 429):
        report["interrompido"] = "Verifique chave/conta/saldo ou limite de consultas antes de continuar"
        return report
    time.sleep(4)
    history_sample, history = probe("/v1/tasks?type=imagen2&page=1&limit=20", key)
    report["consulta_historico"] = history_sample
    history_rows = history.get("data") if history and history.get("success") is True else None
    if isinstance(history_rows, list):
        report["amostra_historico_ate_20_tarefas"] = [
            {"id": row["id"], "status": row.get("status") if row.get("status") in {"doing", "done", "error"} else "inesperado"}
            for row in history_rows[:20] if isinstance(row, dict) and isinstance(row.get("id"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", row["id"])
        ]
    if history_sample.get("http_status") in (401, 403, 429):
        report["interrompido"] = "Histórico indisponível por autenticação ou limite de consultas; sem repetição"
        return report
    for task in tasks:
        task["consultas"] = []
        for no_cache in (False, True):
            time.sleep(4)  # Follows documented 3–5 second task polling guidance.
            result = task_sample(task["task_id"], key, no_cache=no_cache)
            task["consultas"].append(result)
            if result.get("http_status") != 200 or result.get("erro"):
                report["interrompido"] = "Uma consulta falhou; sem repetição automática"
                return report
    report["limites_da_analise"] = [
        "Doing não distingue fila de processamento sem dados adicionais do provedor.",
        "O histórico mostra no máximo 20 tarefas desta conta; não mede a fila global da AI33.",
        "Sem data de término, não é possível determinar quanto tempo a geração levou.",
        "Uma mudança entre consultas pode ser conclusão normal, não prova de cache.",
        "Este relatório omite chave, prompts, URLs das imagens e corpo bruto das respostas.",
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico AI33: apenas consulta tarefas existentes")
    parser.add_argument("project", nargs="?", help="ID do projeto; sem argumento usa o projeto com tarefa AI33 mais recente")
    args = parser.parse_args()
    tasks_root = (ROOT / "storage/tasks").resolve()
    if args.project:
        try:
            identifier = str(UUID(args.project.strip()))
        except ValueError:
            raise DiagnosticError("Informe um ID de projeto válido, como aparece no MPT") from None
        directory = (tasks_root / identifier).resolve()
        if not directory.is_relative_to(tasks_root):
            raise DiagnosticError("Pasta de projeto inválida")
    else:
        candidates = []
        for folder in tasks_root.iterdir() if tasks_root.exists() else []:
            try:
                UUID(folder.name)
            except ValueError:
                continue
            if folder.is_dir() and folder.resolve().is_relative_to(tasks_root):
                files = list(folder.glob("mixed/ai33-*/ai33-image.json"))
                if files:
                    candidates.append((max(f.stat().st_mtime for f in files), folder))
        if not candidates:
            raise DiagnosticError("Nenhum projeto com tarefas AI33 foi encontrado")
        directory = max(candidates, key=lambda item: item[0])[1]
    try:
        configuration = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise DiagnosticError("Não foi possível ler config.toml; confira a configuração local") from None
    app = configuration.get("app", {})
    if not isinstance(app, dict):
        raise DiagnosticError("A seção app da configuração é inválida")
    key = str(app.get("ai33_api_key") or os.environ.get("AI33_API_KEY") or "").strip()
    if not key:
        raise DiagnosticError("Salve sua chave AI33 nas configurações do MPT antes de executar. Não envie a chave no chat.")
    print("Consultando tarefas existentes. Nenhuma imagem será gerada. Aguarde cerca de 30 segundos.")
    report = diagnose(directory, key)
    output = ROOT / "storage/diagnostics"
    output.mkdir(parents=True, exist_ok=True)
    target = output / ("ai33-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    target.write_text(text, encoding="utf-8")
    print(text)
    print("\nRelatório salvo em: " + str(target.relative_to(ROOT)))


if __name__ == "__main__":
    try:
        main()
    except DiagnosticError as exc:
        print(str(exc))
        raise SystemExit(1) from None
    except (ValueError, OSError):
        print("Não foi possível concluir. Verifique o ID/pasta do projeto e a chave AI33 salva no MPT.")
        raise SystemExit(1) from None
