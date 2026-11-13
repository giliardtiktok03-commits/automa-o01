"""Versioned, credential-free channel settings for the first Autopilot delivery."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal


class ChannelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    name: str = Field(min_length=1, max_length=160)
    language: str = Field(default="pt-BR", max_length=32)
    niche: str = Field(default="", max_length=200)
    skill_ids: list[str] = Field(default_factory=list, max_length=8)
    # Explicit preferences for NEW assets only. Saved narration/script are immutable.
    deepinfra_unlimited: bool = False
    image_limit: int = Field(default=120, ge=0, le=120)
    auto_resume: bool = False
    auto_editorial: bool = False
    target_minutes: int = Field(default=20, ge=3, le=30)
    research_model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=160)
    research_backend: Literal['openai', 'public_login'] = 'openai'
    research_domains: list[str] = Field(default_factory=list, max_length=30)
    script_provider: str = Field(default="current", max_length=80)
    script_model: str = Field(default="", max_length=160)

    @field_validator("research_domains")
    @classmethod
    def valid_domains(cls, values):
        import re
        result = []
        for value in values:
            domain = value.strip().lower().removeprefix("www.")
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?\.[a-z]{2,63}", domain) or ".." in domain:
                raise ValueError("Use apenas domínios, sem https, porta ou caminho")
            if domain not in result:
                result.append(domain)
        return result

    @field_validator("name", "language", "niche")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if "\x00" in value:
            raise ValueError("Texto inválido")
        return value

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value):
        if not value:
            raise ValueError("Informe o nome do canal")
        return value

    @field_validator("skill_ids")
    @classmethod
    def valid_skills(cls, values):
        import re
        if len(set(values)) != len(values) or any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", item) for item in values):
            raise ValueError("Seleção de Skills inválida")
        return values
