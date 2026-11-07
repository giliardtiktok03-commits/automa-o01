"""Declarative editorial instructions frozen into a video project."""

from pydantic import BaseModel, Field


class ChannelSkillSnapshot(BaseModel):
    skill_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(default="", max_length=80)
    content: str = Field(min_length=1, max_length=24000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
