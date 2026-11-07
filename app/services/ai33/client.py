"""Contract from the user-supplied AI33 image API documentation, 2026-11-07.

Only task GETs have bounded transient retries. Never retry a paid POST.
"""

import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests


class AI33Error(RuntimeError):
    """Safe diagnostic: never includes upstream bodies, prompts, URLs or keys."""


class _TransientError(AI33Error):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after(value):
    if not isinstance(value, str):
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return 0
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, seconds) if math.isfinite(seconds) else 0


def credits(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AI33Error("AI33 returned invalid credits")
    if not math.isfinite(value) or value < 0:
        raise AI33Error("AI33 returned invalid credits")
    return value


class AI33Client:
    BASE_URL = "https://api.ai33.pro"

    def __init__(self, api_key):
        if not isinstance(api_key, str) or not api_key.strip():
            raise AI33Error("Configure an AI33 API key locally")
        self._key = api_key.strip()

    def _request(self, method, path, **kwargs):
        # A fresh request avoids cookies/session credentials and has no retry adapter.
        try:
            with requests.request(
                method, self.BASE_URL + path,
                headers={"xi-api-key": self._key}, timeout=(15, 90),
                allow_redirects=False, **kwargs,
            ) as response:
                if not 200 <= response.status_code < 300:
                    if method == "GET" and response.status_code in (429, 502, 503, 504):
                        raise _TransientError(
                            f"AI33 HTTP {response.status_code}",
                            _retry_after(response.headers.get("Retry-After")),
                        )
                    raise AI33Error(f"AI33 HTTP {response.status_code}; no automatic retry")
                payload = response.json()
        except (requests.Timeout, requests.ConnectionError):
            if method == "GET":
                raise _TransientError("AI33 consulta sem resposta") from None
            raise AI33Error("AI33 transport failure; paid submission not retried") from None
        except (requests.RequestException, ValueError):
            raise AI33Error("AI33 transport or JSON failure; no automatic retry") from None
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise AI33Error("AI33 returned an unsuccessful or invalid response")
        return payload

    def models(self):
        payload = self._request("GET", "/v1i/models")
        models = payload.get("models")
        if payload.get("success") is not True or not isinstance(models, list):
            raise AI33Error("Invalid AI33 model catalog")
        if not all(isinstance(m, dict) and isinstance(m.get("model_id"), str) for m in models):
            raise AI33Error("Invalid AI33 model entry")
        return models

    def validate(self, model_id, parameters, prompt):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            raise AI33Error("Image prompt must contain 1–4000 characters")
        if re.search(r"@img\d+", prompt, re.IGNORECASE):
            raise AI33Error("Reference assets are not supported by this text-only delivery")
        model = next((m for m in self.models() if m["model_id"] == model_id), None)
        if model is None or model.get("requires_reference_images") is not False:
            raise AI33Error("Model unavailable or text-only capability not confirmed")
        maximum = model.get("max_generations")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            raise AI33Error("Model generation limit is not confirmed")
        if not isinstance(parameters, dict) or set(parameters) != {"aspect_ratio", "resolution"}:
            raise AI33Error("Specify only aspect_ratio and resolution")
        for field, catalog_field in (("aspect_ratio", "aspect_ratios"), ("resolution", "resolutions")):
            if parameters[field] not in model.get(catalog_field, []):
                raise AI33Error(f"Unsupported model parameter: {field}")

    def price(self, model_id, parameters):
        payload = self._request("POST", "/v1i/task/price", json={
            "model_id": model_id, "generations_count": 1,
            "model_parameters": parameters, "assets": 0,
        })
        if payload.get("success") is not True:
            raise AI33Error("Invalid AI33 quote")
        return credits(payload.get("credits"))

    def submit(self, model_id, parameters, prompt):
        # (None, value) forces multipart even without binary reference files.
        fields = {
            "prompt": prompt, "model_id": model_id, "generations_count": "1",
            "model_parameters": json.dumps(parameters, separators=(",", ":")),
        }
        payload = self._request("POST", "/v1i/task/generate-image",
                                files={k: (None, v) for k, v in fields.items()})
        task_id = payload.get("task_id")
        if payload.get("success") is not True or not self.valid_task_id(task_id):
            raise AI33Error("AI33 submission result is unconfirmed")
        return task_id

    @staticmethod
    def valid_task_id(task_id):
        return isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id) is not None

    def task(self, task_id):
        if not self.valid_task_id(task_id):
            raise AI33Error("Invalid AI33 task ID")
        for attempt in range(4):
            try:
                payload = self._request("GET", f"/v1/task/{task_id}")
                break
            except _TransientError as exc:
                delay = max(4 * 2 ** attempt, exc.retry_after)
                if attempt == 3 or delay > 60:
                    raise AI33Error(
                        f"{exc}. Consulta temporariamente indisponível; tarefa preservada. "
                        "Retome mais tarde no mesmo diretório ou confira a tarefa no painel AI33. "
                        "A repetição da consulta não reenvia a geração."
                    ) from None
                logging.getLogger(__name__).warning(
                    "%s. Nova consulta em %.0fs (tentativa %s/4); sem reenviar geração.",
                    exc, delay, attempt + 2,
                )
                time.sleep(delay)
        if payload.get("id") != task_id or payload.get("type") != "imagen2":
            raise AI33Error("AI33 task identity does not match")
        if payload.get("status") not in {"doing", "done", "error"}:
            raise AI33Error("Unknown AI33 task status; resume later without resubmitting")
        return payload
