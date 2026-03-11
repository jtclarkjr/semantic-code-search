from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, SupportsFloat

from app.models.api import SearchRequest
from common.schemas import RepoBundle


class SupabaseSearchRepository:
    def __init__(
        self,
        service_client: Any,
        user_client_factory: Any,
        storage_bucket: str,
    ) -> None:
        self.service_client = service_client
        self.user_client_factory = user_client_factory
        self.storage_bucket = storage_bucket

    def list_repositories(self, access_token: str) -> List[Dict[str, Any]]:
        response = (
            self.user_client_factory(access_token)
            .table("repositories")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return self._as_rows(response.data)

    def get_repository(
        self, repo_id: str, access_token: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        client = self.user_client_factory(access_token) if access_token else self.service_client
        response = client.table("repositories").select("*").eq("id", repo_id).limit(1).execute()
        rows = self._as_rows(response.data)
        return rows[0] if rows else None

    def create_repository(
        self,
        *,
        name: str,
        source_type: str,
        source_ref: str,
        default_branch: Optional[str],
        metadata: Dict[str, Any],
        created_by: str,
    ) -> Dict[str, Any]:
        identity_key = self._repository_identity_key(
            source_type=source_type,
            source_ref=source_ref,
            created_by=created_by,
            default_branch=default_branch,
        )
        payload = {
            "name": name,
            "source_type": source_type,
            "source_ref": source_ref,
            "default_branch": default_branch,
            "identity_key": identity_key,
            "metadata": metadata,
            "created_by": created_by,
        }
        response = (
            self.service_client.table("repositories")
            .upsert(payload, on_conflict="source_type,identity_key")
            .execute()
        )
        rows = self._as_rows(response.data)
        if rows:
            return rows[0]
        lookup = (
            self.service_client.table("repositories")
            .select("*")
            .eq("source_type", source_type)
            .eq("identity_key", identity_key)
            .limit(1)
            .execute()
        )
        return self._as_rows(lookup.data)[0]

    def enqueue_job(
        self,
        repo_id: str,
        job_type: str,
        payload: Dict[str, Any],
        created_by: str,
    ) -> Dict[str, Any]:
        response = (
            self.service_client.table("ingestion_jobs")
            .insert(
                {
                    "repo_id": repo_id,
                    "job_type": job_type,
                    "payload": payload,
                    "created_by": created_by,
                }
            )
            .execute()
        )
        rows = self._as_rows(response.data)
        return rows[0]

    def get_job(self, job_id: str, access_token: str) -> Optional[Dict[str, Any]]:
        response = (
            self.user_client_factory(access_token)
            .table("ingestion_jobs")
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        rows = self._as_rows(response.data)
        return rows[0] if rows else None

    def claim_next_job(self, worker_name: str) -> Optional[Dict[str, Any]]:
        response = self.service_client.rpc(
            "claim_ingestion_job", {"worker_name": worker_name}
        ).execute()
        rows = self._as_rows(response.data)
        return rows[0] if rows else None

    def mark_job_completed(self, job_id: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        response = (
            self.service_client.table("ingestion_jobs")
            .update(
                {
                    "status": "completed",
                    "stats": stats,
                    "error": None,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", job_id)
            .execute()
        )
        rows = self._as_rows(response.data)
        return rows[0] if rows else {"id": job_id, "stats": stats, "status": "completed"}

    def mark_job_failed(self, job_id: str, error: str) -> Dict[str, Any]:
        response = (
            self.service_client.table("ingestion_jobs")
            .update({"status": "failed", "error": error})
            .eq("id", job_id)
            .execute()
        )
        rows = self._as_rows(response.data)
        return rows[0] if rows else {"id": job_id, "error": error, "status": "failed"}

    def replace_repository_snapshot(
        self,
        repo_id: str,
        bundle: RepoBundle,
        embeddings: Sequence[Sequence[SupportsFloat]],
    ) -> Dict[str, Any]:
        if len(bundle.chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts do not match.")

        repository = self.get_repository(repo_id)
        if repository is None:
            raise ValueError(f"Repository {repo_id} not found.")

        next_version = int(repository.get("current_index_version", 0)) + 1

        document_rows = [
            {
                "id": document.document_id,
                "repo_id": repo_id,
                "document_kind": document.kind,
                "path": document.path,
                "language": document.language,
                "title": document.title,
                "external_id": document.external_id,
                "commit_sha": document.commit_sha,
                "content": document.content,
                "metadata": document.metadata,
                "index_version": next_version,
            }
            for document in bundle.documents
        ]
        chunk_rows = [
            {
                "id": chunk.chunk_id,
                "repo_id": repo_id,
                "document_id": chunk.document_id,
                "document_kind": chunk.kind,
                "path": chunk.path,
                "language": chunk.language,
                "preview": chunk.preview,
                "content": chunk.content,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "commit_sha": chunk.commit_sha,
                "metadata": chunk.metadata,
                "index_version": next_version,
                "embedding": self._coerce_float_list(embedding),
            }
            for chunk, embedding in zip(bundle.chunks, embeddings)
        ]

        self._delete_snapshot(repo_id, next_version)
        self._bulk_insert("documents", document_rows)
        self._bulk_insert("chunks", chunk_rows)

        response = (
            self.service_client.table("repositories")
            .update(
                {
                    "current_index_version": next_version,
                    "latest_commit_sha": bundle.latest_commit_sha,
                    "default_branch": bundle.default_branch,
                    "metadata": bundle.metadata,
                }
            )
            .eq("id", repo_id)
            .execute()
        )
        self._delete_old_versions(repo_id, next_version)
        rows = self._as_rows(response.data)
        if rows:
            return rows[0]
        repository["current_index_version"] = next_version
        repository["latest_commit_sha"] = bundle.latest_commit_sha
        repository["default_branch"] = bundle.default_branch
        repository["metadata"] = bundle.metadata
        return repository

    def search_chunks(
        self,
        query_embedding: Sequence[SupportsFloat],
        request: SearchRequest,
        access_token: str,
    ) -> List[Dict[str, Any]]:
        payload = {
            "query_embedding": self._coerce_float_list(query_embedding),
            "match_count": request.limit,
            "repo_ids": request.repo_ids,
            "languages": request.languages,
            "document_kinds": request.content_types,
        }
        response = self.user_client_factory(access_token).rpc("match_chunks", payload).execute()
        return self._as_rows(response.data)

    def _delete_snapshot(self, repo_id: str, index_version: int) -> None:
        self.service_client.table("chunks").delete().eq("repo_id", repo_id).eq(
            "index_version", index_version
        ).execute()
        self.service_client.table("documents").delete().eq("repo_id", repo_id).eq(
            "index_version", index_version
        ).execute()

    def _delete_old_versions(self, repo_id: str, current_version: int) -> None:
        self.service_client.table("chunks").delete().eq("repo_id", repo_id).neq(
            "index_version", current_version
        ).execute()
        self.service_client.table("documents").delete().eq("repo_id", repo_id).neq(
            "index_version", current_version
        ).execute()

    def _bulk_insert(
        self, table_name: str, rows: Iterable[Dict[str, Any]], batch_size: int = 200
    ) -> None:
        batch: List[Dict[str, Any]] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                self.service_client.table(table_name).insert(batch).execute()
                batch.clear()
        if batch:
            self.service_client.table(table_name).insert(batch).execute()

    def _as_rows(self, data: Any) -> List[Dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return list(data)

    def _coerce_float_list(self, values: Sequence[SupportsFloat]) -> List[float]:
        return [float(value) for value in values]

    def _repository_identity_key(
        self,
        *,
        source_type: str,
        source_ref: str,
        created_by: str,
        default_branch: Optional[str],
    ) -> str:
        normalized_source_ref = source_ref.rstrip("/") or source_ref
        if source_type == "local":
            branch = (default_branch or "").strip() or "__default__"
            return f"local:{created_by}:{normalized_source_ref}:{branch}"
        return f"{source_type}:{normalized_source_ref}"
