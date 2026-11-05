"""Contracts for research → original adaptations → narration automation."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Text = Annotated[str, Field(min_length=1, max_length=1000)]


class Contract(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ReferenceInput(Contract):
    title: str = Field(default="", max_length=300)
    url: HttpUrl | None = None
    transcript: str = Field(default="", max_length=30000)

    @model_validator(mode="after")
    def has_reference(self):
        if not (self.title or self.url or self.transcript):
            raise ValueError("provide a reference title, URL or transcript")
        if self.url and (self.url.username or self.url.password):
            raise ValueError("reference URLs must not contain credentials")
        return self


class NexlevVideo(Contract):
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl | None = None
    views: int | None = Field(default=None, ge=0, le=10**15, strict=True)
    channel_median_views: float | None = Field(default=None, ge=0.5, le=10**15, strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def safe_url(self):
        if self.url and (self.url.username or self.url.password):
            raise ValueError("research URLs must not contain credentials")
        return self


class DemandObservation(Contract):
    keyword: str = Field(min_length=1, max_length=200)
    search_volume: int = Field(ge=0, le=10**15, strict=True)
    period: str = Field(min_length=1, max_length=100)
    region: str = Field(default="", max_length=100)


class NexlevResearch(Contract):
    source: Literal["nexlev"] = "nexlev"
    observed_at: datetime | None = None
    notes: str = Field(default="", max_length=12000)
    videos: list[NexlevVideo] = Field(default_factory=list, max_length=50)
    demand: list[DemandObservation] = Field(default_factory=list, max_length=30)
    recurring_patterns: list[Text] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def not_empty(self):
        if not (self.notes or self.videos or self.demand or self.recurring_patterns):
            raise ValueError("supply research results from Nexlev; MPT does not query Nexlev automatically")
        if self.observed_at and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return self


class ResearchRequest(Contract):
    reference: ReferenceInput
    nexlev: NexlevResearch
    target_topic: str = Field(default="", max_length=300)
    outlier_threshold: float = Field(default=2.0, ge=1, le=100, allow_inf_nan=False)


class DecompositionRequest(ResearchRequest):
    provider: Literal["ollama", "openai"] = "ollama"
    language: str = Field(default="pt-BR", min_length=1, max_length=30)
    requirements: str = Field(default="", max_length=2000)


class Adaptation(Contract):
    id: Literal[1, 2, 3]
    title: str = Field(min_length=1, max_length=300)
    theme: Text
    angle: Text
    format: Text
    promise: Text
    research_fit: Text
    originality: Text
    score: int = Field(ge=0, le=100, strict=True)
    outline: list[Text] = Field(min_length=3, max_length=12)


class EditorialDecision(Contract):
    theme: Text
    angle: Text
    format: Text
    promise: Text
    adaptations: list[Adaptation] = Field(min_length=3, max_length=3)
    selected_id: Literal[1, 2, 3]
    selection_reason: Text

    @model_validator(mode="after")
    def coherent_selection(self):
        if {proposal.id for proposal in self.adaptations} != {1, 2, 3}:
            raise ValueError("adaptation IDs must be exactly 1, 2 and 3")
        selected = next(p for p in self.adaptations if p.id == self.selected_id)
        if selected.score != max(p.score for p in self.adaptations):
            raise ValueError("the AI must select a highest-scoring adaptation")
        signatures = {(p.angle.casefold(), p.format.casefold(), p.promise.casefold()) for p in self.adaptations}
        if len(signatures) != 3:
            raise ValueError("provide three distinct adaptations")
        return self

    @property
    def selected(self):
        return next(p for p in self.adaptations if p.id == self.selected_id)


class WorkflowRequest(DecompositionRequest):
    workflow_id: UUID | None = None
    target_duration_minutes: int = Field(default=10, ge=1, le=30)


class EditorialScriptRequest(DecompositionRequest):
    decision: EditorialDecision
    target_duration_minutes: int = Field(default=10, ge=1, le=30)
