from __future__ import annotations

import asyncio
from typing import Any, Dict

from common.schemas import RepoBundle


class IngestionService:
    def __init__(
        self,
        repository: Any,
        github_ingestion_service: Any,
        local_bundle_service: Any,
        embedding_service: Any,
        embedding_batch_size: int = 16,
    ) -> None:
        self.repository = repository
        self.github_ingestion_service = github_ingestion_service
        self.local_bundle_service = local_bundle_service
        self.embedding_service = embedding_service
        self.embedding_batch_size = embedding_batch_size

    async def process_next_job(self, worker_name: str) -> bool:
        job = await asyncio.to_thread(self.repository.claim_next_job, worker_name)
        if job is None:
            return False

        try:
            repo = await asyncio.to_thread(self.repository.get_repository, job["repo_id"])
            if repo is None:
                raise ValueError(f"Repository {job['repo_id']} not found.")
            bundle = await asyncio.to_thread(self._build_bundle, job, repo)
            embeddings = await self._embed_chunks(bundle)
            updated_repo = await asyncio.to_thread(
                self.repository.replace_repository_snapshot,
                repo["id"],
                bundle,
                embeddings,
            )
            await asyncio.to_thread(
                self.repository.mark_job_completed,
                job["id"],
                {
                    "documents_indexed": len(bundle.documents),
                    "chunks_indexed": len(bundle.chunks),
                    "index_version": updated_repo.get("current_index_version"),
                },
            )
        except Exception as exc:  # pragma: no cover - hit in integration/error scenarios
            await asyncio.to_thread(self.repository.mark_job_failed, job["id"], str(exc))
        return True

    def _build_bundle(self, job: Dict[str, Any], repo: Dict[str, Any]) -> RepoBundle:
        payload = job.get("payload", {})
        if job["job_type"] == "github_sync":
            return self.github_ingestion_service.fetch_bundle(
                repo_name=repo["name"],
                clone_url=payload.get("clone_url", repo["source_ref"]),
                default_branch=payload.get("default_branch") or repo.get("default_branch"),
            )
        if job["job_type"] == "local_bundle":
            return self.local_bundle_service.fetch_bundle(payload["bundle_object_path"])
        raise ValueError(f"Unsupported job type: {job['job_type']}")

    async def _embed_chunks(self, bundle: RepoBundle) -> list[list[float]]:
        chunk_texts = [chunk.content for chunk in bundle.chunks]
        embeddings: list[list[float]] = []
        for start in range(0, len(chunk_texts), self.embedding_batch_size):
            batch = chunk_texts[start : start + self.embedding_batch_size]
            batch_embeddings = await asyncio.to_thread(self.embedding_service.embed_texts, batch)
            embeddings.extend(batch_embeddings)
            await asyncio.sleep(0)
        return embeddings
