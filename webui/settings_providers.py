"""Local configuration eligibility for the General settings shortcuts.

These checks never authenticate, refresh tokens, inspect model catalogs or probe a
provider. Eligibility means configuration is present, not that a remote call works.
"""

from pathlib import Path
import shutil

from app.config import config
from app.models.llm_provider import LLM_PROVIDER_REGISTRY
from app.services import (
    infistar_video,
    jalapeno_video,
    loomloom,
    material,
    metaso_minimax,
    muapi,
    ofox,
    volcengine_seedance,
)


def _text(value):
    return str(value or "").strip()


def _has_keys(value):
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        return False
    return any(isinstance(item, str) and item.strip() for item in values)


def _claude_cli_available(configured_path):
    command = configured_path or "claude"
    return bool(
        shutil.which(command) or (configured_path and Path(configured_path).is_file())
    )


def configured_llm_providers(settings, oauth_status):
    """Return registry IDs with locally configured required fields/credentials."""
    configured = []
    for provider in LLM_PROVIDER_REGISTRY:
        key = _text(settings.get(provider.config_key("api_key")))
        saved_model = _text(settings.get(provider.config_key("model_name")))
        saved_base = _text(settings.get(provider.config_key("base_url")))
        model = provider.resolve_model_name(saved_model)
        base = provider.resolve_base_url(saved_base)
        if provider.provider_id == "ollama":
            base = base or config.get_default_ollama_base_url()
        if provider.provider_id in {"openai_codex", "openai_chatgpt", "kimi_code"}:
            if not oauth_status.get(provider.provider_id, False):
                continue
        elif provider.provider_id == "claude_code":
            if not _claude_cli_available(
                _text(settings.get(provider.config_key("cli_path")))
            ):
                continue
        elif not provider.requires_api_key and not (
            key
            or (saved_model and saved_model != provider.default_model)
            or (saved_base and saved_base != provider.effective_default_base_url)
        ):
            # Registry defaults alone do not demonstrate a configured local gateway.
            continue
        if provider.requires_api_key and not key:
            continue
        if provider.requires_model_name and not model:
            continue
        if provider.requires_base_url and not base:
            continue
        if any(
            field.required
            and not _text(
                settings.get(provider.config_key(field.config_suffix))
                or field.default_value
            )
            for field in provider.extra_fields
        ):
            continue
        configured.append(provider.provider_id)
    return tuple(configured)


def configured_material_providers(settings, groups, codex_connected=False):
    """Return configured providers per material category, preserving its order."""
    enabled = {
        provider: _has_keys(settings.get(f"{provider}_api_keys"))
        for provider in ("pexels", "pixabay", "coverr", "wavespeed")
    }
    from app.services.ai33 import provider as ai33_provider
    enabled["ai33_image"] = ai33_provider.is_enabled(settings)
    from app.services import flow_browser
    enabled["google_flow"] = settings.get("google_flow_access_mode") == "manual_import"
    if not enabled["google_flow"] and settings.get("google_flow_project_url"):
        try:
            flow_browser.validate(settings.get("google_flow_profile", "principal"), settings["google_flow_project_url"])
            enabled["google_flow"] = True
        except ValueError:
            pass
    from app.services import grok_image
    enabled["grok_image"] = grok_image.is_enabled(settings)
    enabled.update(
        {
            "metaso_minimax": metaso_minimax.is_enabled(settings),
            "ofox": ofox.is_enabled(settings),
            "volcengine_seedance": volcengine_seedance.is_enabled(settings),
            "infistar": infistar_video.is_enabled(settings),
            "jalapeno": jalapeno_video.is_enabled(settings),
            "muapi": muapi.is_enabled(settings),
            "openai_image": material.is_openai_image_enabled(settings),
            "codex_image": False,
        }
    )
    try:
        loomloom.video_settings_from_mapping(settings)
    except (loomloom.LoomLoomConfigurationError, ValueError, TypeError):
        enabled["loomloom"] = False
    else:
        enabled["loomloom"] = True
    return {
        group: tuple(provider for provider in providers if enabled.get(provider, False))
        for group, providers in groups.items()
        if group != "local"
    }
