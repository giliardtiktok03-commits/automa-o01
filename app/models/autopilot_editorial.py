"""Explicit contracts for title-to-research/script jobs. No credentials in snapshots."""
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.models.autopilot import ChannelProfile
from app.models.channel_skill import ChannelSkillSnapshot


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EditorialSnapshot(Record):
    channel: ChannelProfile
    skills: list[ChannelSkillSnapshot] = Field(default_factory=list, max_length=8)
    script_provider: str = Field(min_length=1, max_length=80)
    script_model: str = Field(min_length=1, max_length=160)
    script_base_url: str = Field(default="", max_length=500)


class Reference(Record):
    id: str = Field(pattern=r"^S[1-9][0-9]?$" )
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=1500)


class Quote(Record):
    source_id: str = Field(pattern=r"^S[1-9][0-9]?$" )
    text: str = Field(min_length=20, max_length=500)


class Claim(Record):
    id: str = Field(pattern=r"^C[1-9][0-9]?$" )
    statement: str = Field(min_length=10, max_length=1500)
    evidence: list[Quote] = Field(min_length=1, max_length=4)


class Research(Record):
    summary: str = Field(min_length=30, max_length=12000)
    ready: StrictBool
    gaps: list[str] = Field(default_factory=list, max_length=20)
    sources: list[Reference] = Field(min_length=2, max_length=6)
    claims: list[Claim] = Field(min_length=4, max_length=40)

    @model_validator(mode="after")
    def references_exist(self):
        source_ids = [s.id for s in self.sources]
        claim_ids = [c.id for c in self.claims]
        if len(set(source_ids)) != len(source_ids) or len(set(claim_ids)) != len(claim_ids):
            raise ValueError("IDs de fontes/afirmações duplicados")
        if any(q.source_id not in source_ids for c in self.claims for q in c.evidence):
            raise ValueError("Afirmação referencia uma fonte inexistente")
        return self


class Review(Record):
    approved: StrictBool
    issues: list[str] = Field(default_factory=list, max_length=30)
    @model_validator(mode="after")
    def coherent(self):
        if self.approved and self.issues:
            raise ValueError("Revisão contraditória")
        return self


class Section(Record):
    narration: str = Field(min_length=40, max_length=16000)
    claim_ids: list[str] = Field(min_length=1, max_length=40)


class Script(Record):
    title: str = Field(min_length=1, max_length=300)
    sections: list[Section] = Field(min_length=3, max_length=80)


class Package(Record):
    description: str = Field(min_length=30, max_length=3500)
    tags: list[str] = Field(min_length=1, max_length=30)
    hashtags: list[str] = Field(min_length=1, max_length=6)
    thumbnail_brief: str = Field(min_length=30, max_length=2000)


class BlueprintReview(Review):
    # Explicit coverage prevents a generic approval from approving unreviewed beats.
    approved_beats: list[int] = Field(default_factory=list, max_length=9)
