"""Shared archive contracts; defaults never enable network activity."""
from dataclasses import dataclass, field, asdict
from typing import Protocol, Literal
from pydantic import BaseModel, Field


class ArchiveSettings(BaseModel):
    enabled: bool = False
    mode: Literal['historical_plus_stock','historical_research_only'] = 'historical_plus_stock'
    loc_enabled: bool = True
    nara_enabled: bool = True
    wikimedia_enabled: bool = True
    auto_download_rights_cleared: bool = True
    photographs: bool = True
    documents: bool = True
    maps: bool = True
    footage: bool = False
    candidates_per_scene: int = Field(default=5, ge=1, le=20)
    max_downloads_per_video: int = Field(default=30, ge=1, le=300)
    request_timeout_seconds: float = Field(default=20, ge=2, le=60)
    cache_ttl_hours: float = Field(default=24, ge=0, le=720)
    request_interval_seconds: float = Field(default=2, ge=.2, le=60)
    loc_interval_seconds: float = Field(default=2, ge=.2, le=60)
    nara_interval_seconds: float = Field(default=2, ge=.2, le=60)
    wikimedia_interval_seconds: float = Field(default=2, ge=.2, le=60)
    nara_monthly_limit: int = Field(default=1000, ge=1, le=100000)
    max_retries: int = Field(default=1, ge=0, le=2)
    max_file_mb: int = Field(default=50, ge=1, le=500)
    language: str = 'en'
    preferred_period: str = ''
    preserve_aspect: bool = True
    show_credits: bool = True
    min_score: float = Field(default=35, ge=0, le=100)
    llm_queries: bool = False
    user_agent: str = 'MoneyPrinterTurbo-HistoricalArchive/1.0 (https://github.com/giliardtiktok03-commits/automa-o01)'

    def media_types(self):
        return [name for name, flag in [('photograph',self.photographs),('document',self.documents),
                 ('map',self.maps),('video',self.footage)] if flag]


@dataclass
class ArchiveCandidate:
    provider: str
    record_id: str
    title: str
    description: str = ''
    date_created: str = ''
    creator: str = ''
    institution: str = ''
    media_type: str = 'photograph'
    thumbnail_url: str = ''
    source_url: str = ''
    download_url: str = ''
    rights_statement: str = ''
    license_url: str = ''
    attribution: str = ''
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class ArchiveProvider(Protocol):
    def search(self, query: str, media_types: list[str], limit: int) -> list[ArchiveCandidate]: ...
    def health_check(self) -> dict: ...


class ArchiveError(ValueError):
    pass


class ArchiveDisabled(ArchiveError):
    pass


class ArchivePending(ArchiveError):
    def __init__(self, message, task_id, scene_id):
        super().__init__(message)
        self.task_id, self.scene_id = task_id, scene_id
