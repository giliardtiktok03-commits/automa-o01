"""One-image jobs with crash-safe checkpoints and credential-free downloads."""

import hashlib
import io
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import socket
import tempfile
import time
from urllib.parse import urljoin, urlsplit
import warnings

from filelock import FileLock
from PIL import Image
import requests

from .client import AI33Error, credits


class AI33PendingError(AI33Error):
    """Known paid task is still pending, not a failed generation."""

    def __init__(self, task_id):
        self.task_id = task_id
        super().__init__(f"AI33 ainda está processando a imagem. Tarefa {task_id} preservada; retome o mesmo projeto sem reenviar a geração.")


def _atomic(path, content):
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _public_https(url):
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        if parts.port not in (None, 443):
            raise ValueError()
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError()
    except (ValueError, OSError, TypeError):
        raise AI33Error("AI33 image URL must resolve to public HTTPS") from None


def download_png(url):
    """Never forward API authentication/cookies to the image host or redirects."""
    for redirect in range(4):
        _public_https(url)
        try:
            with requests.get(url, stream=True, timeout=(15, 90), allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if redirect == 3 or not location:
                        raise AI33Error("AI33 image redirect limit exceeded")
                    url = urljoin(url, location)
                    continue
                if response.status_code != 200:
                    raise AI33Error(f"AI33 image download HTTP {response.status_code}")
                data = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    data.extend(chunk)
                    if len(data) > 25 * 1024 * 1024:
                        raise AI33Error("AI33 image exceeds 25 MiB")
        except requests.RequestException:
            raise AI33Error("AI33 image download failed; resume the same task") from None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.width * image.height > 50_000_000:
                        raise AI33Error("AI33 image exceeds 50 megapixels")
                    image.load()
                    output = io.BytesIO()
                    image.convert("RGB").save(output, format="PNG")
                    return output.getvalue()
        except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise AI33Error("AI33 result is not a supported safe image") from None
    raise AI33Error("AI33 image download did not complete")


class ImageJob:
    """Use a unique persistent directory per intended image, including on restart.

    The credit cap gates the quote, not the provider's eventual actual charge.
    A quote has no documented price lock. No automatic new paid attempt is made.
    """

    def __init__(self, client, directory):
        self.client = client
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self.directory / "ai33-image.json"
        self.output = self.directory / "image.png"

    def _save(self, state):
        _atomic(self.checkpoint, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))

    def run(self, *, model_id, parameters, prompt, max_credits, max_polls=150, before_submit=None,
            wait_seconds=None, on_status=None, existing_only=False):
        credits(max_credits)
        if isinstance(max_polls, bool) or not isinstance(max_polls, int) or max_polls < 1:
            raise AI33Error("max_polls must be a positive integer")
        if wait_seconds is not None and (isinstance(wait_seconds, bool) or not isinstance(wait_seconds, (int, float))
                                         or not math.isfinite(wait_seconds) or not 0 < wait_seconds <= 7200):
            raise AI33Error("wait_seconds must be positive and at most 7200")
        def notify(task_id, status, progress=None):
            if on_status is not None:
                try:
                    on_status(task_id, status, progress)
                except Exception:
                    logging.getLogger(__name__).warning("AI33 progress notification failed; paid task retained")
        specification = {"model_id": model_id, "parameters": parameters, "prompt": prompt}
        fingerprint = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
        with FileLock(str(self.checkpoint) + ".lock", timeout=0):
            if self.checkpoint.exists():
                state = json.loads(self.checkpoint.read_text(encoding="utf-8"))
                if state.get("version") != 1 or state.get("fingerprint") != fingerprint:
                    raise AI33Error("AI33 checkpoint differs from this image request")
                if state.get("status") == "saved":
                    if self.output.exists() and hashlib.sha256(self.output.read_bytes()).hexdigest() == state.get("sha256"):
                        return self.output
                    # A known task can be downloaded again without another generation.
                if not state.get("task_id"):
                    raise AI33Error("Unconfirmed paid submission; reconcile in AI33 before any new attempt")
                if state.get("status") == "error":
                    raise AI33Error("AI33 task failed; no automatic paid retry or assumed safety refusal")
            else:
                if existing_only:
                    raise AI33Error("Registro AI33 ausente; geração paga não será reenviada")
                self.client.validate(model_id, parameters, prompt)
                estimate = self.client.price(model_id, parameters)
                if estimate > max_credits:
                    raise AI33Error("AI33 quote exceeds the authorized credit cap")
                state = {"version": 1, "provider": "ai33", "model_id": model_id,
                         "fingerprint": fingerprint, "quoted_credits": estimate,
                         "status": "submission_unconfirmed"}
                # A crash or timeout after this write must never trigger another POST.
                self._save(state)
                if before_submit is not None:
                    before_submit()
                state["task_id"] = self.client.submit(model_id, parameters, prompt)
                state["status"] = "submitted"
                self._save(state)
            notify(state["task_id"], state["status"])
            deadline = time.monotonic() + wait_seconds if wait_seconds is not None else None
            attempt = 0
            while True:
                result = self.client.task(state["task_id"])
                state["status"] = result["status"]
                if "credit_cost" in result:
                    state["actual_credits"] = credits(result["credit_cost"])
                self._save(state)
                notify(state["task_id"], state["status"], result.get("progress"))
                if state["status"] == "error":
                    raise AI33Error("AI33 task failed; inspect provider history, no automatic retry")
                if state["status"] == "done":
                    metadata = result.get("metadata")
                    images = metadata.get("result_images") if isinstance(metadata, dict) else None
                    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
                        raise AI33Error("AI33 completed task has an invalid image result")
                    content = download_png(images[0].get("imageUrl"))
                    _atomic(self.output, content)
                    state.update(status="saved", sha256=hashlib.sha256(content).hexdigest(), file="image.png")
                    self._save(state)
                    return self.output
                attempt += 1
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AI33PendingError(state["task_id"])
                    time.sleep(min(4, remaining))
                elif attempt >= max_polls:
                    raise AI33PendingError(state["task_id"])
                else:
                    time.sleep(4)
