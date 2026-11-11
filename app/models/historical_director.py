"""Typed contracts for the optional documentary director. No executable Skill content."""
from typing import Literal
from pydantic import Field, StrictBool, model_validator
from app.models.autopilot_editorial import Record


class Weights(Record):
    curiosity: int = Field(default=25, ge=0, le=100)
    originality: int = Field(default=25, ge=0, le=100)
    thumbnail: int = Field(default=20, ge=0, le=100)
    retention: int = Field(default=15, ge=0, le=100)
    sources: int = Field(default=15, ge=0, le=100)

    @model_validator(mode='after')
    def total(self):
        if sum(self.model_dump().values()) != 100:
            raise ValueError('Os pesos editoriais devem somar 100')
        return self


class ImageRef(Record):
    image_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    width: int = Field(ge=64, le=4096)
    height: int = Field(ge=64, le=4096)


class Request(Record):
    skill_enabled: Literal[True] = True
    title: str = Field(min_length=1, max_length=300)
    reference_script: str = Field(default='', max_length=120000)
    angle_enabled: bool = True
    selection_mode: Literal['manual', 'automatic'] = 'manual'
    automatic_multiple: bool = False
    automatic_top_n: int = Field(default=1, ge=1, le=5)
    thumbnail_reference_enabled: bool = False
    thumbnails: list[ImageRef] = Field(default_factory=list, max_length=3)
    central_angle: str = Field(default='', max_length=1000)
    visual_identity: str = Field(default='', max_length=1500)
    weights: Weights = Field(default_factory=Weights)
    vision_model: str = Field(default='gpt-4.1-mini', min_length=1, max_length=160)
    max_image_mb: int = Field(default=10, ge=1, le=20)
    on_failure: Literal['pause_queue', 'skip'] = 'pause_queue'
    publish_mode: Literal['off'] = 'off'  # Fail closed until media/YouTube QA is connected.

    @model_validator(mode='after')
    def controls(self):
        if any('\x00' in value for value in [self.title,self.reference_script,self.central_angle,self.visual_identity]):
            raise ValueError('As referências devem conter texto válido, sem caracteres nulos')
        if self.automatic_top_n > 1 and not self.automatic_multiple:
            raise ValueError('Autorize explicitamente múltiplos vídeos no modo automático')
        if len({x.image_id for x in self.thumbnails}) != len(self.thumbnails):
            raise ValueError('Thumbnails de referência repetidas')
        return self


class Scores(Record):
    curiosity: int = Field(ge=0, le=100)
    originality: int = Field(ge=0, le=100)
    thumbnail: int = Field(ge=0, le=100)
    retention: int = Field(ge=0, le=100)
    sources: int = Field(ge=0, le=100)


class Gates(Record):
    on_topic: StrictBool
    credible: StrictBool
    differentiated: StrictBool


class Angle(Record):
    angle_id: str = Field(pattern=r'^angle_0[1-5]$')
    name: str = Field(min_length=3, max_length=160)
    title_en: str = Field(min_length=10, max_length=300)
    title_pt: str = Field(min_length=10, max_length=300)
    title_local: str = Field(default='', max_length=300)
    core_question: str = Field(min_length=10, max_length=1000)
    point_of_view: str = Field(min_length=10, max_length=1000)
    conflict: str = Field(min_length=10, max_length=1000)
    emotional_trigger: str = Field(min_length=3, max_length=500)
    originality_delta: str = Field(min_length=20, max_length=1500)
    story_framework: Literal['A','B','C','D','E','F']
    hook_proposal: str = Field(min_length=20, max_length=1500)
    payoff_promise: str = Field(min_length=20, max_length=1500)
    thumbnail_hook: str = Field(min_length=20, max_length=1000)
    source_feasibility: str = Field(min_length=20, max_length=1500)
    historical_caveats: list[str] = Field(default_factory=list, max_length=20)
    supporting_claim_ids: list[str] = Field(min_length=1, max_length=40)
    gates: Gates
    scores: Scores
    score_reason: str = Field(min_length=20, max_length=1500)


class Analysis(Record):
    theme: str = Field(min_length=10, max_length=1500)
    reference_angle: str = Field(min_length=10, max_length=1500)
    reference_structure: list[str] = Field(min_length=1, max_length=30)
    reference_limitations: list[str] = Field(default_factory=list, max_length=20)
    central_channel_angle: str = Field(max_length=1500)
    alternatives: list[Angle] = Field(min_length=5, max_length=5)

    @model_validator(mode='after')
    def ids(self):
        if {a.angle_id for a in self.alternatives} != {f'angle_0{i}' for i in range(1,6)}:
            raise ValueError('São necessários cinco IDs de ângulo distintos')
        return self


class AngleDecision(Record):
    angle_id: str = Field(pattern=r'^angle_0[1-5]$')
    eligible: StrictBool
    reasons: list[str] = Field(min_length=1, max_length=20)


class AngleReview(Record):
    decisions: list[AngleDecision] = Field(min_length=5, max_length=5)


class VisualItem(Record):
    image_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    visual_hook: str = Field(min_length=10, max_length=1500)
    composition: str = Field(min_length=10, max_length=1500)
    palette_lighting: str = Field(min_length=10, max_length=1000)
    visible_text: str = Field(max_length=1000)
    mobile_readability: str = Field(min_length=5, max_length=1000)
    reusable_mechanisms: list[str] = Field(min_length=1, max_length=20)
    do_not_copy: list[str] = Field(min_length=1, max_length=20)
    limitations: list[str] = Field(min_length=1, max_length=20)


class VisualAnalysis(Record):
    images: list[VisualItem] = Field(min_length=1, max_length=3)
    shared_curiosity: str = Field(min_length=10, max_length=1500)
    incompatibilities: list[str] = Field(default_factory=list, max_length=20)


class Concept(Record):
    name: str = Field(min_length=3, max_length=100)
    visual_promise: str = Field(min_length=20, max_length=1500)
    dominant_object: str = Field(min_length=3, max_length=500)
    emotion: str = Field(min_length=3, max_length=500)
    title_hook_alignment: str = Field(min_length=20, max_length=1500)
    historical_scene: str = Field(min_length=10, max_length=1500)
    claim_ids: list[str] = Field(min_length=1, max_length=40)
    layout: str = Field(min_length=10, max_length=1500)
    text: str = Field(max_length=100)
    palette_contrast: str = Field(min_length=10, max_length=1000)
    accuracy_constraints: list[str] = Field(min_length=1, max_length=20)
    prompt_en: str = Field(min_length=40, max_length=3500)
    negative_prompt: str = Field(min_length=10, max_length=1500)


class ThumbnailBrief(Record):
    concepts: list[Concept] = Field(min_length=3, max_length=3)
    reference_adaptation: str = Field(min_length=20, max_length=2000)


class Distinction(Record):
    left: str = Field(pattern=r'^angle_0[1-5]$')
    right: str = Field(pattern=r'^angle_0[1-5]$')
    differentiated: StrictBool
    reason: str = Field(min_length=10, max_length=1500)


class EligibilityReview(AngleReview):
    pairs: list[Distinction] = Field(min_length=10, max_length=10)


class ReferenceOverview(Record):
    theme: str = Field(min_length=10, max_length=1500)
    reference_angle: str = Field(min_length=10, max_length=1500)
    reference_structure: list[str] = Field(min_length=1, max_length=30)
    reference_limitations: list[str] = Field(default_factory=list, max_length=20)
