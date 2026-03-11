from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

DocumentKind = Literal["code", "documentation", "commit"]
SourceType = Literal["github", "local"]


def _uuid_str() -> str:
    return str(uuid4())


class SourceDocument(BaseModel):
    document_id: str = Field(default_factory=_uuid_str)
    kind: DocumentKind
    path: str
    content: str
    title: Optional[str] = None
    language: Optional[str] = None
    external_id: Optional[str] = None
    commit_sha: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SourceChunk(BaseModel):
    chunk_id: str = Field(default_factory=_uuid_str)
    document_id: str
    kind: DocumentKind
    path: str
    content: str
    preview: str
    start_line: int = 1
    end_line: int = 1
    language: Optional[str] = None
    commit_sha: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RepoBundle(BaseModel):
    repo_name: str
    source_type: SourceType
    source_ref: str
    default_branch: Optional[str] = None
    latest_commit_sha: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    documents: List[SourceDocument] = Field(default_factory=list)
    chunks: List[SourceChunk] = Field(default_factory=list)
