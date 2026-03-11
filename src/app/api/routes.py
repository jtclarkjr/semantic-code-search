from __future__ import annotations

import asyncio
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.auth import UserContext, get_current_user
from app.services.embedding import EmbeddingServiceError
from app.models.api import (
    GitHubRepositoryCreateRequest,
    JobResponse,
    LocalRepositoryCreateRequest,
    LoginRequest,
    LoginResponse,
    RepositoryQueuedResponse,
    RepositoryResponse,
    RepositorySyncRequest,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

router = APIRouter()


def get_container(request: Request):
    return request.app.state.container


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, container=Depends(get_container)) -> LoginResponse:
    try:
        result = await asyncio.to_thread(
            container.auth_service.login, payload.email, payload.password
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    result["public_config"] = {
        "supabase_url": container.settings.supabase_url,
        "supabase_publishable_key": container.settings.supabase_publishable_key,
        "supabase_storage_bucket": container.settings.supabase_storage_bucket,
    }
    return LoginResponse(**result)


@router.get("/repos", response_model=List[RepositoryResponse])
async def list_repositories(
    user: UserContext = Depends(get_current_user),
    container=Depends(get_container),
) -> List[RepositoryResponse]:
    rows = await asyncio.to_thread(container.repository.list_repositories, user.access_token)
    return [RepositoryResponse(**row) for row in rows]


@router.post(
    "/repos/github", response_model=RepositoryQueuedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_github_repository(
    payload: GitHubRepositoryCreateRequest,
    user: UserContext = Depends(get_current_user),
    container=Depends(get_container),
) -> RepositoryQueuedResponse:
    repository = await asyncio.to_thread(
        container.repository.create_repository,
        name=payload.name,
        source_type="github",
        source_ref=payload.clone_url,
        default_branch=payload.default_branch,
        metadata=payload.metadata,
        created_by=user.user_id,
    )
    job = await asyncio.to_thread(
        container.repository.enqueue_job,
        repository["id"],
        "github_sync",
        {"clone_url": payload.clone_url, "default_branch": payload.default_branch},
        user.user_id,
    )
    return RepositoryQueuedResponse(
        repository=RepositoryResponse(**repository),
        job=JobResponse(**job),
    )


@router.post(
    "/repos/local", response_model=RepositoryQueuedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_local_repository(
    payload: LocalRepositoryCreateRequest,
    user: UserContext = Depends(get_current_user),
    container=Depends(get_container),
) -> RepositoryQueuedResponse:
    source_ref = payload.source_ref or payload.bundle_object_path
    repository = await asyncio.to_thread(
        container.repository.create_repository,
        name=payload.name,
        source_type="local",
        source_ref=source_ref,
        default_branch=payload.default_branch,
        metadata=payload.metadata,
        created_by=user.user_id,
    )
    job = await asyncio.to_thread(
        container.repository.enqueue_job,
        repository["id"],
        "local_bundle",
        {"bundle_object_path": payload.bundle_object_path},
        user.user_id,
    )
    return RepositoryQueuedResponse(
        repository=RepositoryResponse(**repository),
        job=JobResponse(**job),
    )


@router.post(
    "/repos/{repo_id}/sync", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED
)
async def sync_repository(
    repo_id: str,
    payload: RepositorySyncRequest,
    user: UserContext = Depends(get_current_user),
    container=Depends(get_container),
) -> JobResponse:
    repository = await asyncio.to_thread(
        container.repository.get_repository, repo_id, user.access_token
    )
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    if repository["source_type"] == "github":
        job_type = "github_sync"
        job_payload = {
            "clone_url": repository["source_ref"],
            "default_branch": payload.default_branch or repository.get("default_branch"),
        }
    else:
        if not payload.bundle_object_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="bundle_object_path is required when syncing a local repository.",
            )
        job_type = "local_bundle"
        job_payload = {"bundle_object_path": payload.bundle_object_path}

    job = await asyncio.to_thread(
        container.repository.enqueue_job,
        repo_id,
        job_type,
        job_payload,
        user.user_id,
    )
    return JobResponse(**job)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    user: UserContext = Depends(get_current_user),
    container=Depends(get_container),
) -> JobResponse:
    job = await asyncio.to_thread(container.repository.get_job, job_id, user.access_token)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return JobResponse(**job)


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    user: UserContext = Depends(get_current_user),
    container=Depends(get_container),
) -> SearchResponse:
    try:
        query_embedding = await asyncio.to_thread(
            container.embedding_service.embed_query, payload.query
        )
    except EmbeddingServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    rows = await asyncio.to_thread(
        container.repository.search_chunks,
        query_embedding,
        payload,
        user.access_token,
    )

    results = [SearchResult(**row) for row in _dedupe_results(rows, payload.limit)]
    return SearchResponse(results=results)


def _dedupe_results(rows: List[dict], limit: int) -> List[dict]:
    seen = set()
    deduped: List[dict] = []
    for row in rows:
        key = (row.get("repo_id"), row.get("path"), row.get("start_line"), row.get("end_line"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped
