"""MPT adapter. Keys stay in runtime config, never in VideoParams/manifests."""

import json
import os
from pathlib import Path

from app.config import config
from app.services import generation_progress
from .client import AI33Client, AI33Error, credits
from .images import ImageJob


def api_key(settings=None):
    settings = config.app if settings is None else settings
    return str(settings.get("ai33_api_key") or os.environ.get("AI33_API_KEY") or "").strip()


def is_enabled(settings=None):
    settings = config.app if settings is None else settings
    return bool(api_key(settings) and str(settings.get("ai33_image_model") or "").strip())


def freeze(params, settings=None):
    settings = config.app if settings is None else settings
    defaults = {"ai33_model": ("ai33_image_model", ""),
                "ai33_resolution": ("ai33_image_resolution", "2K"),
                "ai33_quality": ("ai33_image_quality", ""),
                "ai33_max_credits": ("ai33_image_max_credits", 1000)}
    for field, (key, default) in defaults.items():
        if getattr(params, field) is None:
            value = settings.get(key, default)
            try:
                setattr(params, field, float(value) if field == "ai33_max_credits" else str(value or "").strip())
            except (ValueError, TypeError):
                raise AI33Error("O teto de créditos AI33 deve ser um número finito e não negativo") from None
    if not api_key(settings) or not params.ai33_model:
        raise AI33Error("Configure a chave e o modelo AI33.Pro em Configurar fontes de material")
    credits(params.ai33_max_credits)


def parameters(params):
    values = {"aspect_ratio": getattr(params.video_aspect, "value", params.video_aspect)}
    if params.ai33_resolution:
        values["resolution"] = params.ai33_resolution
    if params.ai33_quality:
        values["quality"] = params.ai33_quality
    return values


def generate(params, prompt, directory, *, before_submit=None):
    freeze(params)
    generation_progress.stage("ai33_image")
    path = ImageJob(AI33Client(api_key()), directory).run(
        model_id=params.ai33_model, parameters=parameters(params), prompt=prompt,
        max_credits=params.ai33_max_credits, before_submit=before_submit,
    )
    checkpoint = json.loads((Path(directory) / "ai33-image.json").read_text(encoding="utf-8"))
    return path, {k: checkpoint[k] for k in ("task_id", "model_id", "quoted_credits", "actual_credits") if k in checkpoint}
