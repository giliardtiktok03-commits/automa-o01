"""Evidence-aware editorial plans; never a media generation request."""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Engine = Literal['institutional_chronology', 'covert_mission', 'plan_vs_reality',
                 'intelligence_mystery', 'decision_chain', 'technology_vs_constraints', 'rise_and_fall']
Novelty = Literal['duplicate', 'overlap_requires_distinct_angle', 'related_but_distinct', 'new', 'insufficient_information']


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class MemoryCheck(Record):
    status: Novelty
    matched_video_ids: list[str] = Field(default_factory=list, max_length=100)
    explanation: str = Field(min_length=1, max_length=2000)


class Source(Record):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(default='', max_length=1500)
    excerpt: str = Field(min_length=1, max_length=8000)
    interpretation: Literal['documented', 'disputed', 'hypothesis', 'unknown'] = 'unknown'
    # A supplied excerpt is not independently fetched or authenticated by this module.
    provenance: Literal['user_supplied'] = 'user_supplied'


class Beat(Record):
    new_information: str = Field(min_length=1, max_length=1500)
    why_it_matters: str = Field(min_length=1, max_length=1000)
    open_question: str = Field(min_length=1, max_length=1000)
    evidence_needed: str = Field(min_length=1, max_length=1500)
    confidence: Literal['verified', 'supported_but_disputed', 'needs_research', 'unknown'] = 'needs_research'
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class EvidenceQuote(Record):
    source_id: str = Field(min_length=1, max_length=80)
    excerpt: str = Field(min_length=1, max_length=2000)


class EditorialClaim(Record):
    statement: str = Field(min_length=1, max_length=1500)
    classification: Literal['documented_fact', 'allegation', 'inference', 'research_gap']
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence_quotes: list[EvidenceQuote] = Field(default_factory=list, max_length=10)
    caveat: str = Field(default='', max_length=1500)
    material: bool = True


class CentralConflict(Record):
    tension: str = Field(min_length=1, max_length=1500)
    stakes: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    uncertainty: str = Field(min_length=1, max_length=1500)


class EpisodeBlueprint(Record):
    project: Literal['Beyond the Archives'] = 'Beyond the Archives'
    module_version: Literal['story_intelligence_v1'] = 'story_intelligence_v1'
    editorial_id: str = Field(default='', max_length=64)
    distinct_angle: str = Field(default='', max_length=2000)
    input_topic: str = Field(min_length=1, max_length=1000)
    title_working: str = Field(min_length=1, max_length=1000)
    subject: str = Field(min_length=1, max_length=1000)
    temporal_window: str = Field(default='unknown', max_length=300)
    geography: str = Field(default='unknown', max_length=300)
    editorial_memory_check: MemoryCheck
    primary_story_engine: Engine
    secondary_story_engine: Engine | None = None
    reason_for_structure: str = Field(min_length=1, max_length=2500)
    alternative_engines_note: str = Field(min_length=1, max_length=2000)
    core_question: str = Field(min_length=1, max_length=1500)
    title_promise: str = Field(min_length=1, max_length=1500)
    target_duration_minutes: int = Field(default=20, ge=1, le=180)
    target_word_count_range: list[int] = Field(default_factory=lambda: [2600, 2900], min_length=2, max_length=2)
    opening_hook_strategy: str = Field(min_length=1, max_length=1500)
    narrative_beats: list[Beat] = Field(default_factory=list, max_length=9)
    research_questions: list[str] = Field(default_factory=list, max_length=30)
    source_register: list[Source] = Field(default_factory=list, max_length=30)
    visual_evidence_ideas: list[str] = Field(default_factory=list, max_length=20)
    risk_flags: list[str] = Field(default_factory=list, max_length=30)
    readiness: Literal['research_required', 'needs_revision', 'ready_to_write'] = 'research_required'
    revision_notes: list[str] = Field(default_factory=list, max_length=40)
    evidence_reviewed: bool = False
    distinct_angle_reviewed: bool = False
    approved_for_script: bool = False
    memory_digest: str = ''
    analysis_method: Literal['local_provisional', 'central_model'] = 'local_provisional'
    analysis_revision: int = Field(default=1, ge=1, le=2)
    analysis_provider: str = Field(default='', max_length=80)
    analysis_model: str = Field(default='', max_length=160)
    fallback_reason: Literal['', 'not_configured', 'selected_local', 'api_unavailable', 'invalid_response', 'duplicate_blocked'] = ''
    narrative_potential: str = Field(default='', max_length=3000)
    central_conflicts: list[CentralConflict] = Field(default_factory=list, max_length=9)
    progression_strategy: str = Field(default='', max_length=2500)
    ending_strategy: str = Field(default='', max_length=2000)
    pacing_strategy: str = Field(default='', max_length=2000)
    claim_register: list[EditorialClaim] = Field(default_factory=list, max_length=40)
