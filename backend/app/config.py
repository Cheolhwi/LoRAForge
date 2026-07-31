from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    data_root: str = "."
    dino_model_id: str = "facebook/dinov3-vitl16-pretrain-lvd1689m"
    locate_anything_endpoint: str = ""
    locate_anything_model_id: str = "mlx-community/LocateAnything-3B-4bit"
    locate_anything_timeout_seconds: int = 180
    locate_anything_max_tokens: int = 1024
    pixai_model_name: str = "v0.9"
    pixai_model_id: str = "pixai-labs/pixai-tagger-v0.9"
    pixai_runtime_model_id: str = "deepghs/pixai-tagger-v0.9-onnx"
    pixai_storage_threshold: float = 0.10
    pixai_feature_threshold: float = 0.35
    pixai_caption_threshold: float = Field(default=0.50, ge=0.05, le=0.95)
    pixai_caption_max_tags: int = Field(default=48, ge=8, le=100)
    pixai_caption_hard_max_tags: int = Field(default=64, ge=8, le=128)
    pixai_caption_exclusive_margin: float = Field(default=0.15, ge=0.0, le=1.0)
    pixai_caption_pair_margin: float = Field(default=0.15, ge=0.0, le=1.0)
    pixai_caption_abstract_threshold: float = Field(default=0.65, ge=0.05, le=0.99)
    pixai_caption_remove_all_text_tags: bool = False
    pixai_parent_rules_path: str = ""
    pixai_parent_rules_strict: bool = False
    min_megapixels: int = 1_000_000
    complete_linkage_similarity: float = 0.90
    graph_similarity: float = 0.65
    graph_top_k: int = 20
    core_degree: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_caption_limits(self) -> "Settings":
        if self.pixai_caption_hard_max_tags < self.pixai_caption_max_tags:
            raise ValueError(
                "PIXAI_CAPTION_HARD_MAX_TAGS must be greater than or equal to "
                "PIXAI_CAPTION_MAX_TAGS"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
