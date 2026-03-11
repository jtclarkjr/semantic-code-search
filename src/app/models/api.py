from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class PublicClientConfig(BaseModel):
    supabase_url: str
    supabase_publishable_key: str
    supabase_storage_bucket: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[int] = None
    token_type: str = "bearer"
    user: Dict[str, Any] = Field(default_factory=dict)
    public_config: Optional[PublicClientConfig] = None


class GitHubRepositoryCreateRequest(BaseModel):
    name: str
    clone_url: str
    default_branch: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LocalRepositoryCreateRequest(BaseModel):
    name: str
    bundle_object_path: str
    source_ref: Optional[str] = None
    default_branch: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RepositorySyncRequest(BaseModel):
    bundle_object_path: Optional[str] = None
    default_branch: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RepositoryResponse(BaseModel):
    id: str
    name: str
    source_type: str
    source_ref: str
    default_branch: Optional[str] = None
    latest_commit_sha: Optional[str] = None
    current_index_version: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    repo_id: Optional[str] = None
    job_type: str
    status: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    stats: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class RepositoryQueuedResponse(BaseModel):
    repository: RepositoryResponse
    job: JobResponse


class SearchRequest(BaseModel):
    query: str
    repo_ids: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    content_types: Optional[List[str]] = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    chunk_id: str
    repo_id: str
    repo_name: Optional[str] = None
    path: str
    language: Optional[str] = None
    document_kind: str
    preview: str
    content: str
    start_line: int
    end_line: int
    score: float
    commit_sha: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: List[SearchResult]
