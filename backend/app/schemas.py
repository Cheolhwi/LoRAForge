from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PipelineOptions(BaseModel):
    deduplicate: bool = True
    resolution_filter: bool = True
    embedding: bool = True
    clustering: bool = True
    graph_filter: bool = True
    locate: bool = True
    retry: bool = True

    @model_validator(mode="after")
    def normalize_dependencies(self):
        if not self.embedding:
            self.clustering = False
            self.graph_filter = False
        if not self.locate:
            self.retry = False
        return self


class JobCreate(BaseModel):
    source_dir: str = Field(min_length=1)
    output_dir: str | None = None
    similarity_model: Literal["dinov3", "pixai"] = "dinov3"
    minimum_pixels: int | None = Field(default=None, ge=65_536, le=100_000_000)
    complete_linkage_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    graph_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    pipeline_options: PipelineOptions = Field(default_factory=PipelineOptions)
    seed: int | None = None


class PipelineEvent(BaseModel):
    id: int
    job_id: str
    stage: str
    status: str
    message: str
    progress: float = 0.0
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class JobSummary(BaseModel):
    job_id: str
    status: str
    workflow: str = "filtering"
    similarity_model: str = "dinov3"
    minimum_pixels: int | None = None
    complete_linkage_similarity: float | None = None
    graph_similarity: float | None = None
    pipeline_options: dict[str, bool] = Field(default_factory=dict)
    source_dir: str
    output_dir: str | None
    current_stage: str | None
    progress: float
    started_at: datetime
    finished_at: datetime | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ManifestItem(BaseModel):
    source: str
    output: str | None = None
    cluster_id: int
    candidate_role: str
    locate_attempt: int
    status: str
    reason: str | None = None


class JobManifest(BaseModel):
    job_id: str
    items: list[ManifestItem]


class CurationStart(BaseModel):
    lora_prefix: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )

    @field_validator("lora_prefix", mode="before")
    @classmethod
    def normalize_prefix(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PixAIJobCreate(CurationStart):
    source_dir: str = Field(min_length=1)
    output_dir: str | None = None


class CurationFinalize(BaseModel):
    target_size: int = Field(ge=1, le=10_000)
    people_count_target: dict[str, float] = Field(
        default_factory=lambda: {"1": 0.85, "2": 0.12, "3_plus": 0.03}
    )
    framing_target: dict[str, float] = Field(
        default_factory=lambda: {"full_body": 0.30, "half_body": 0.50, "headshot": 0.20}
    )
    outdoors_target: dict[str, float] = Field(
        default_factory=lambda: {"true": 0.40, "false": 0.60}
    )
    caption_threshold: float = Field(default=0.50, ge=0.05, le=0.95)
    denylist: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_targets(self):
        expected = {
            "people_count_target": {"1", "2", "3_plus"},
            "framing_target": {"full_body", "half_body", "headshot"},
            "outdoors_target": {"true", "false"},
        }
        for field_name, expected_keys in expected.items():
            values = getattr(self, field_name)
            if set(values) != expected_keys:
                raise ValueError(
                    f"{field_name} must contain exactly: {', '.join(sorted(expected_keys))}"
                )
            if any(value < 0 for value in values.values()) or sum(values.values()) <= 0:
                raise ValueError(f"{field_name} values must be non-negative with a positive sum")
        self.denylist = sorted(
            {tag.strip() for tag in self.denylist if tag.strip()},
            key=str.casefold,
        )
        return self
