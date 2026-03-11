from decimal import Decimal
from types import SimpleNamespace

from app.models.api import SearchRequest
from app.repositories.supabase_repository import SupabaseSearchRepository


class FakeRpcClient:
    def __init__(self) -> None:
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"chunk_id": "1"}]))


def test_search_chunks_uses_rpc_payload() -> None:
    client = FakeRpcClient()
    repository = SupabaseSearchRepository(
        service_client=SimpleNamespace(),
        user_client_factory=lambda _: client,
        storage_bucket="repo-bundles",
    )

    results = repository.search_chunks(
        [0.1, 0.2],
        SearchRequest(query="debounce", repo_ids=["repo-1"], languages=["typescript"], limit=5),
        "token",
    )

    assert results == [{"chunk_id": "1"}]
    name, payload = client.calls[0]
    assert name == "match_chunks"
    assert payload["repo_ids"] == ["repo-1"]
    assert payload["languages"] == ["typescript"]
    assert payload["match_count"] == 5


def test_search_chunks_coerces_query_embedding_values_to_builtin_floats() -> None:
    client = FakeRpcClient()
    repository = SupabaseSearchRepository(
        service_client=SimpleNamespace(),
        user_client_factory=lambda _: client,
        storage_bucket="repo-bundles",
    )

    repository.search_chunks(
        [Decimal("0.1"), Decimal("0.2")],
        SearchRequest(query="websocket", limit=5),
        "token",
    )

    _, payload = client.calls[0]
    assert payload["query_embedding"] == [0.1, 0.2]
    assert all(type(value) is float for value in payload["query_embedding"])


def test_local_repository_identity_key_scopes_by_user_path_and_branch() -> None:
    repository = SupabaseSearchRepository(
        service_client=SimpleNamespace(),
        user_client_factory=lambda _: SimpleNamespace(),
        storage_bucket="repo-bundles",
    )

    main_key = repository._repository_identity_key(
        source_type="local",
        source_ref="/Users/demo/react-frontend",
        created_by="user-1",
        default_branch="main",
    )
    feature_key = repository._repository_identity_key(
        source_type="local",
        source_ref="/Users/demo/react-frontend",
        created_by="user-1",
        default_branch="feature/search",
    )
    other_user_key = repository._repository_identity_key(
        source_type="local",
        source_ref="/Users/demo/react-frontend",
        created_by="user-2",
        default_branch="main",
    )

    assert main_key == "local:user-1:/Users/demo/react-frontend:main"
    assert feature_key == "local:user-1:/Users/demo/react-frontend:feature/search"
    assert other_user_key == "local:user-2:/Users/demo/react-frontend:main"
    assert len({main_key, feature_key, other_user_key}) == 3
