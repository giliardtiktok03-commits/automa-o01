"""Native Runware REST image tasks; no SDK dependency or paid POST retries.

Contract: github.com/runware/runware-python (transport/rest.py,
types/task_map.py, client.py), reviewed for this integration.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
from uuid import UUID, uuid4

from filelock import FileLock
import requests

from app.config import config
from app.services import generation_progress
from app.services.ai33.images import download_png
from app.services.ai33 import AI33Error
from app.utils.atomic_files import write_bytes_atomic

API = "https://api.runware.ai/v1"
CONTENT = "https://content.runware.ai"
DEFAULT_MODEL = "runware:100@1"  # Official registry: bfl-flux-1-schnell
CURATED = {"runware:100@1": "FLUX.1 Schnell", "runware:101@1": "FLUX.1 Dev"}


class RunwareError(ValueError):
    pass


class RunwarePending(RunwareError):
    def __init__(self, task_id):
        self.task_id = task_id
        super().__init__(f"Imagem Runware ainda pendente. Tarefa {task_id} preservada; retome o mesmo projeto.")


def api_key(settings=None):
    settings = config.app if settings is None else settings
    return str(settings.get("runware_api_key") or os.environ.get("RUNWARE_API_KEY") or "").strip()


def is_enabled(settings=None):
    return bool(api_key(settings))


def freeze(params, settings=None):
    settings = config.app if settings is None else settings
    defaults = {"runware_model": ("runware_image_model", DEFAULT_MODEL),
                "runware_steps": ("runware_image_steps", 4),
                "runware_size": ("runware_image_size", 1024)}
    for field, (key, default) in defaults.items():
        if getattr(params, field) is None:
            try:
                value = settings.get(key, default)
                setattr(params, field, str(value).strip() if field == "runware_model" else int(value))
            except (ValueError, TypeError):
                raise RunwareError("Configuração de imagem Runware inválida") from None
    if not api_key(settings):
        raise RunwareError("Configure a chave Runware em Configurar fontes de material")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+", params.runware_model or ""):
        raise RunwareError("Informe o identificador AIR do modelo Runware")
    if params.runware_size not in (1024, 2048) or not 0 <= params.runware_steps <= 100:
        raise RunwareError("Use tamanho 1024/2048 e passos entre 0 e 100")


def parameters(params):
    aspect = getattr(params.video_aspect, "value", params.video_aspect)
    size = params.runware_size
    width, height = {"16:9": (size, size * 9 // 16), "9:16": (size * 9 // 16, size), "1:1": (size, size)}[aspect]
    result = {"model": params.runware_model, "width": width, "height": height}
    if params.runware_steps:
        result["steps"] = params.runware_steps
    return result


class Client:
    def __init__(self, key):
        if not key:
            raise RunwareError("Configure a chave Runware no MPT")
        self._key = key

    def post(self, task):
        try:
            with requests.post(API, headers={"Authorization": "Bearer " + self._key},
                               json=[task], timeout=(15, 60), allow_redirects=False) as response:
                if not 200 <= response.status_code < 300:
                    raise RunwareError(f"Runware HTTP {response.status_code}; solicitação não repetida")
                body = response.json()
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, RunwareError):
                raise
            raise RunwareError("Runware sem resposta válida; tarefa preservada, sem repetir geração") from None
        if not isinstance(body, dict):
            raise RunwareError("Resposta Runware inválida")
        if body.get("errors") or body.get("error"):
            errors = body.get("errors")
            error = errors[0] if isinstance(errors, list) and errors else body.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            code = code if isinstance(code, str) and code != self._key and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", code) else "provider_error"
            raise RunwareError(f"Runware: {code}; sem reformulação ou nova geração automática")
        rows = body.get("data")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RunwareError("Runware não retornou uma lista de resultados válida")
        return rows

    def search(self, query="FLUX"):
        task_id = str(uuid4())
        rows = self.post({"taskType": "modelSearch", "taskUUID": task_id, "search": query[:100],
                          "source": "official", "category": "checkpoint", "limit": 20, "offset": 0})
        matching = [row for row in rows if row.get("taskUUID") == task_id and isinstance(row.get("results"), list)]
        if len(matching) != 1:
            raise RunwareError("Busca de modelos Runware sem identidade confirmada")
        return [{"air": row["air"], "name": str(row.get("name") or row["air"])[:160]}
                for row in matching[0]["results"] if isinstance(row, dict) and isinstance(row.get("air"), str)]

    @staticmethod
    def pricing(model):
        # Public metadata; credentials must never be sent to this other host.
        try:
            with requests.get(CONTENT + "/models/" + quote(model, safe="") + "/pricing",
                              timeout=(15, 30), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise RunwareError("Referência pública de preços indisponível; consulte a Runware")
                body = response.json()
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, RunwareError):
                raise
            raise RunwareError("Não foi possível consultar a referência de preços") from None
        if not isinstance(body, dict):
            raise RunwareError("Referência de preços inválida")
        return {"overview": str(body.get("pricingOverview") or "")[:2000],
                "examples": [{"configuration": str(row.get("configuration") or "")[:300], "price": str(row.get("price") or "")[:100]}
                             for row in (body.get("pricingExamples") if isinstance(body.get("pricingExamples"), list) else [])[:10] if isinstance(row, dict)]}


def generate(params, prompt, directory, *, before_submit=None, settings=None, existing_only=False):
    freeze(params, settings)
    settings = config.app if settings is None else settings
    try:
        wait = float(settings.get("runware_image_wait_minutes", 10)) * 60
    except (ValueError, TypeError):
        raise RunwareError("Configure a espera Runware entre 1 e 120 minutos") from None
    if not math.isfinite(wait) or not 60 <= wait <= 7200:
        raise RunwareError("Configure a espera Runware entre 1 e 120 minutos")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise RunwareError("O prompt Runware deve ter de 1 a 4000 caracteres")
    spec = {**parameters(params), "positivePrompt": prompt}
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    ledger, image = folder / "runware-image.json", folder / "image.png"
    client = Client(api_key(settings))
    def save(state):
        write_bytes_atomic(ledger, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))
    with FileLock(str(ledger) + ".lock", timeout=0):
        if ledger.exists():
            state = json.loads(ledger.read_text(encoding="utf-8"))
            if state.get("version") != 1 or state.get("fingerprint") != fingerprint:
                raise RunwareError("As configurações diferem do teste/projeto Runware salvo")
            try:
                task_id = str(UUID(state["task_id"]))
            except (KeyError, ValueError, TypeError):
                raise RunwareError("ID Runware salvo inválido; revise antes de outra geração") from None
            if state.get("status") == "saved" and image.exists() and hashlib.sha256(image.read_bytes()).hexdigest() == state.get("sha256"):
                return image, {key: state[key] for key in ("task_id", "model", "cost_usd") if key in state}
            rows = None
        else:
            if existing_only:
                raise RunwareError("Registro Runware ausente; não será reenviada uma geração paga")
            task_id = str(uuid4())
            state = {"version": 1, "provider": "runware_image", "task_id": task_id,
                     "model": params.runware_model, "fingerprint": fingerprint, "status": "submission_unconfirmed"}
            save(state)  # UUID persisted before POST, also recovers lost ACKs.
            if before_submit:
                before_submit()
            generation_progress.submitting("runware_image")
            rows = client.post({"taskType": "imageInference", "taskUUID": task_id, **spec,
                                "numberResults": 1, "deliveryMethod": "async", "outputType": "URL",
                                "outputFormat": "PNG", "includeCost": True})
            state["status"] = "submitted"
            save(state)
        deadline = time.monotonic() + wait
        while True:
            generation_progress.remote("runware_image", task_id, "processing")
            if rows is None:
                rows = client.post({"taskType": "getResponse", "taskUUID": task_id})
            matching = [row for row in rows if row.get("taskUUID") == task_id]
            if rows and len(matching) != len(rows):
                raise RunwareError("A resposta Runware contém outra tarefa; nenhum arquivo foi usado")
            for row in matching:
                if row.get("status") == "error" or row.get("error"):
                    raise RunwareError("A tarefa Runware retornou erro; sem novo envio automático")
            images = [row for row in matching if row.get("imageURL")]
            if images:
                if len(images) != 1 or images[0].get("NSFWContent") is True:
                    raise RunwareError("Resultado Runware precisa de revisão; nenhum novo envio foi feito")
                result = images[0]
                if result.get("taskType") not in (None, "imageInference"):
                    raise RunwareError("Resultado Runware não corresponde à geração de imagem")
                if isinstance(result.get("cost"), (int, float)) and not isinstance(result["cost"], bool) and math.isfinite(result["cost"]) and result["cost"] >= 0:
                    state["cost_usd"] = result["cost"]
                state["status"] = "generated"
                save(state)
                generation_progress.downloading()
                try:
                    content = download_png(result["imageURL"])
                except AI33Error:
                    raise RunwareError("Não foi possível baixar a imagem Runware; retome a mesma tarefa, sem nova geração") from None
                write_bytes_atomic(image, content)
                state.update(status="saved", sha256=hashlib.sha256(content).hexdigest())
                save(state)
                return image, {key: state[key] for key in ("task_id", "model", "cost_usd") if key in state}
            state["status"] = "processing"
            save(state)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RunwarePending(task_id)
            time.sleep(min(3, remaining))
            rows = None
