from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import ec
import jwt
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.api import SearchRequest
from app.services.embedding import EmbeddingServiceError


class FakeRepository:
    def __init__(self) -> None:
        self.last_local_create = None

    def list_repositories(self, access_token):
        return [
            {
                "id": "repo-1",
                "name": "demo",
                "source_type": "github",
                "source_ref": "https://github.com/example/demo",
                "default_branch": "main",
                "latest_commit_sha": None,
                "current_index_version": 1,
                "metadata": {},
            }
        ]

    def search_chunks(self, query_embedding, request: SearchRequest, access_token):
        assert access_token
        assert request.query == "debounce function for Vue"
        return [
            {
                "chunk_id": "chunk-1",
                "repo_id": "repo-1",
                "repo_name": "demo",
                "path": "src/useDebounce.ts",
                "language": "typescript",
                "document_kind": "code",
                "preview": "export function useDebounce()",
                "content": "export function useDebounce() { return null }",
                "start_line": 1,
                "end_line": 1,
                "score": 0.99,
                "metadata": {},
            },
            {
                "chunk_id": "chunk-2",
                "repo_id": "repo-1",
                "repo_name": "demo",
                "path": "src/useDebounce.ts",
                "language": "typescript",
                "document_kind": "code",
                "preview": "export function useDebounce()",
                "content": "export function useDebounce() { return null }",
                "start_line": 1,
                "end_line": 1,
                "score": 0.97,
                "metadata": {},
            },
        ]

    def create_repository(self, **kwargs):
        self.last_local_create = kwargs
        return {
            "id": "repo-local-1",
            "name": kwargs["name"],
            "source_type": kwargs["source_type"],
            "source_ref": kwargs["source_ref"],
            "default_branch": kwargs["default_branch"],
            "latest_commit_sha": None,
            "current_index_version": 0,
            "metadata": kwargs["metadata"],
        }

    def enqueue_job(self, repo_id, job_type, payload, created_by):
        return {
            "id": "job-1",
            "repo_id": repo_id,
            "job_type": job_type,
            "status": "pending",
            "payload": payload,
            "stats": {},
            "error": None,
        }


class FakeContainer:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            app_name="test-app",
            api_prefix="/v1",
            supabase_url="https://demo.supabase.co",
            supabase_publishable_key="sb_publishable_demo",
            supabase_storage_bucket="repo-bundles",
        )
        self.token_verifier = SimpleNamespace(
            decode=lambda token: {
                "sub": "user-123",
                "email": "dev@example.com",
                "role": "authenticated",
            }
        )
        self.repository = FakeRepository()
        self.embedding_service = SimpleNamespace(embed_query=lambda query: [0.1, 0.2, 0.3])
        self.auth_service = SimpleNamespace(
            login=lambda email, password: {
                "access_token": "token-123",
                "refresh_token": "refresh-123",
                "expires_at": 1234567890,
                "token_type": "bearer",
                "user": {"id": "user-123", "email": email},
            }
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _bearer_token() -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    return jwt.encode(
        {
            "sub": "user-123",
            "email": "dev@example.com",
            "iss": "https://example.supabase.co/auth/v1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        private_key,
        algorithm="ES256",
        headers={"kid": "current-key"},
    )


def test_list_repositories_requires_authentication() -> None:
    app = create_app(container=FakeContainer())
    with TestClient(app) as client:
        response = client.get("/v1/repos")

        assert response.status_code == 401


def test_login_returns_public_client_config() -> None:
    app = create_app(container=FakeContainer())
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            json={"email": "dev@example.com", "password": "secret"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "token-123"
        assert body["public_config"] == {
            "supabase_url": "https://demo.supabase.co",
            "supabase_publishable_key": "sb_publishable_demo",
            "supabase_storage_bucket": "repo-bundles",
        }


def test_search_returns_deduped_results() -> None:
    app = create_app(container=FakeContainer())
    with TestClient(app) as client:
        response = client.post(
            "/v1/search",
            headers={"Authorization": f"Bearer {_bearer_token()}"},
            json={"query": "debounce function for Vue", "limit": 10},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["path"] == "src/useDebounce.ts"


def test_create_local_repo_passes_default_branch() -> None:
    container = FakeContainer()
    app = create_app(container=container)
    with TestClient(app) as client:
        response = client.post(
            "/v1/repos/local",
            headers={"Authorization": f"Bearer {_bearer_token()}"},
            json={
                "name": "react-frontend",
                "bundle_object_path": "local/react-frontend-main.json.gz",
                "source_ref": "/Users/demo/react-frontend",
                "default_branch": "main",
            },
        )

        assert response.status_code == 202
        assert container.repository.last_local_create["default_branch"] == "main"


def test_search_returns_503_when_embedding_backend_is_unavailable() -> None:
    container = FakeContainer()
    container.embedding_service = SimpleNamespace(
        embed_query=lambda query: (_ for _ in ()).throw(
            EmbeddingServiceError("embedding backend unavailable")
        )
    )
    app = create_app(container=container)
    with TestClient(app) as client:
        response = client.post(
            "/v1/search",
            headers={"Authorization": f"Bearer {_bearer_token()}"},
            json={"query": "websocket", "limit": 10},
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "embedding backend unavailable"
