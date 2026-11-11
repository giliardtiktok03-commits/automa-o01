"""Versioned, credential-free channel settings for the first Autopilot delivery."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


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
