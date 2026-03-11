from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from supabase import Client

from app.core.auth import SupabaseJWTVerifier
from app.core.config import Settings, get_settings
from app.core.supabase import build_supabase_client
from app.repositories.supabase_repository import SupabaseSearchRepository
from app.services.auth_service import AuthService
from app.services.embedding import EmbeddingService
from app.services.github_ingest import GitHubIngestionService
from app.services.ingestion import IngestionService
from app.services.local_bundle import LocalBundleService
from app.services.worker import JobWorker
from common.chunking import ChunkingService
from common.repo_scan import RepoScanner


def build_user_client_factory(settings: Settings) -> Callable[[str], Client]:
    def factory(access_token: str) -> Client:
        return build_supabase_client(
            settings.supabase_url,
            settings.supabase_publishable_key,
            access_token,
        )

    return factory


@dataclass
class AppContainer:
    settings: Settings
    public_client: Client
    service_client: Client
    token_verifier: SupabaseJWTVerifier
    repository: SupabaseSearchRepository
    auth_service: AuthService
    embedding_service: EmbeddingService
    github_ingestion_service: GitHubIngestionService
    local_bundle_service: LocalBundleService
    ingestion_service: IngestionService
    worker: JobWorker
    worker_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self.settings.job_worker_enabled and self.worker_task is None:
            self.worker_task = asyncio.create_task(
                self.worker.run(), name="semantic-code-search-worker"
            )

    async def stop(self) -> None:
        if self.worker_task is None:
            return
        await self.worker.stop()
        await self.worker_task
        self.worker_task = None


def build_container(settings: Optional[Settings] = None) -> AppContainer:
    settings = settings or get_settings()
    public_client = build_supabase_client(settings.supabase_url, settings.supabase_publishable_key)
    service_client = build_supabase_client(settings.supabase_url, settings.supabase_secret_key)
    user_client_factory = build_user_client_factory(settings)

    chunking_service = ChunkingService()
    repo_scanner = RepoScanner(
        chunking_service=chunking_service,
        max_file_bytes=settings.max_file_bytes,
        max_commit_messages=settings.max_commit_messages,
    )
    repository = SupabaseSearchRepository(
        service_client=service_client,
        user_client_factory=user_client_factory,
        storage_bucket=settings.supabase_storage_bucket,
    )
    embedding_service = EmbeddingService(
        model_name=settings.embedding_model_name,
        dimensions=settings.embedding_dimensions,
        device=settings.embedding_device,
        use_stub_embeddings=settings.use_stub_embeddings,
    )
    github_ingestion_service = GitHubIngestionService(
        repo_scanner=repo_scanner,
        github_token=settings.github_token,
        clone_depth=settings.github_clone_depth,
    )
    local_bundle_service = LocalBundleService(
        storage_client=service_client,
        bucket_name=settings.supabase_storage_bucket,
    )
    ingestion_service = IngestionService(
        repository=repository,
        github_ingestion_service=github_ingestion_service,
        local_bundle_service=local_bundle_service,
        embedding_service=embedding_service,
        embedding_batch_size=settings.embedding_batch_size,
    )
    worker = JobWorker(
        ingestion_service=ingestion_service,
        poll_interval_seconds=settings.job_poll_interval_seconds,
    )
    return AppContainer(
        settings=settings,
        public_client=public_client,
        service_client=service_client,
        token_verifier=SupabaseJWTVerifier(
            issuer=settings.resolved_supabase_jwt_issuer,
            audience=settings.supabase_jwt_audience,
            jwks_url=settings.resolved_supabase_jwks_url,
            jwks_cache_ttl_seconds=settings.supabase_jwks_cache_ttl_seconds,
        ),
        repository=repository,
        auth_service=AuthService(public_client),
        embedding_service=embedding_service,
        github_ingestion_service=github_ingestion_service,
        local_bundle_service=local_bundle_service,
        ingestion_service=ingestion_service,
        worker=worker,
    )
