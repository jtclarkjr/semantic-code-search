from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SCS_",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "development"
    app_name: str = "semantic-code-search"
    api_prefix: str = "/v1"

    supabase_url: str = "https://example.supabase.co"
    supabase_publishable_key: str = "sb_publishable_example"
    supabase_secret_key: str = "sb_secret_example"
    supabase_jwt_issuer: Optional[str] = None
    supabase_jwt_audience: Optional[str] = None
    supabase_jwks_cache_ttl_seconds: int = Field(default=300, ge=0)
    supabase_storage_bucket: str = "repo-bundles"

    github_token: Optional[str] = None

    embedding_model_name: str = "jinaai/jina-embeddings-v2-base-code"
    embedding_dimensions: int = 768
    embedding_device: Optional[str] = None
    use_stub_embeddings: bool = False
    embedding_batch_size: int = Field(default=16, ge=1)

    job_worker_enabled: bool = True
    job_poll_interval_seconds: float = 3.0
    github_clone_depth: int = 50
    max_file_bytes: int = Field(default=200_000, ge=1)
    max_commit_messages: int = Field(default=200, ge=1)

    @field_validator("supabase_jwt_issuer", "supabase_jwt_audience", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def resolved_supabase_jwt_issuer(self) -> str:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def resolved_supabase_jwks_url(self) -> str:
        return f"{self.resolved_supabase_jwt_issuer}/.well-known/jwks.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
