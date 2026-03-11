import asyncio

from common.schemas import RepoBundle, SourceChunk, SourceDocument
from app.services.ingestion import IngestionService


class FakeRepository:
    def __init__(self) -> None:
        self.completed = None
        self.failed = None

    def claim_next_job(self, worker_name):
        return {
            "id": "job-1",
            "repo_id": "repo-1",
            "job_type": "local_bundle",
            "payload": {"bundle_object_path": "bundle.gz"},
        }

    def get_repository(self, repo_id):
        return {
            "id": repo_id,
            "name": "demo",
            "source_ref": "/tmp/demo",
            "current_index_version": 0,
        }

    def replace_repository_snapshot(self, repo_id, bundle, embeddings):
        assert repo_id == "repo-1"
        assert len(bundle.documents) == 1
        assert len(embeddings) == 1
        return {"id": repo_id, "current_index_version": 1}

    def mark_job_completed(self, job_id, stats):
        self.completed = (job_id, stats)

    def mark_job_failed(self, job_id, error):
        self.failed = (job_id, error)


class FakeLocalBundleService:
    def fetch_bundle(self, object_path):
        assert object_path == "bundle.gz"
        document = SourceDocument(
            kind="code", path="main.py", language="python", content="def run():\n    pass\n"
        )
        chunk = SourceChunk(
            document_id=document.document_id,
            kind="code",
            path=document.path,
            language="python",
            content=document.content,
            preview="def run():",
            start_line=1,
            end_line=2,
        )
        return RepoBundle(
            repo_name="demo",
            source_type="local",
            source_ref="/tmp/demo",
            documents=[document],
            chunks=[chunk],
        )


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_ingestion_service_processes_local_bundle_job() -> None:
    embedder = FakeEmbedder()
    service = IngestionService(
        repository=FakeRepository(),
        github_ingestion_service=None,
        local_bundle_service=FakeLocalBundleService(),
        embedding_service=embedder,
    )

    processed = asyncio.run(service.process_next_job("worker-1"))

    assert processed is True
    assert service.repository.completed[0] == "job-1"
    assert service.repository.failed is None
    assert embedder.calls == [["def run():\n    pass\n"]]


def test_ingestion_service_embeds_in_batches() -> None:
    class MultiChunkLocalBundleService:
        def fetch_bundle(self, object_path):
            assert object_path == "bundle.gz"
            documents = [
                SourceDocument(
                    kind="code",
                    path=f"file_{index}.py",
                    language="python",
                    content=f"def run_{index}():\n    pass\n",
                )
                for index in range(3)
            ]
            chunks = [
                SourceChunk(
                    document_id=document.document_id,
                    kind="code",
                    path=document.path,
                    language="python",
                    content=document.content,
                    preview=f"def run_{index}():",
                    start_line=1,
                    end_line=2,
                )
                for index, document in enumerate(documents)
            ]
            return RepoBundle(
                repo_name="demo",
                source_type="local",
                source_ref="/tmp/demo",
                documents=documents,
                chunks=chunks,
            )

    class MultiChunkRepository(FakeRepository):
        def replace_repository_snapshot(self, repo_id, bundle, embeddings):
            assert len(embeddings) == 3
            return {"id": repo_id, "current_index_version": 1}

    embedder = FakeEmbedder()
    service = IngestionService(
        repository=MultiChunkRepository(),
        github_ingestion_service=None,
        local_bundle_service=MultiChunkLocalBundleService(),
        embedding_service=embedder,
        embedding_batch_size=2,
    )

    processed = asyncio.run(service.process_next_job("worker-1"))

    assert processed is True
    assert embedder.calls == [
        ["def run_0():\n    pass\n", "def run_1():\n    pass\n"],
        ["def run_2():\n    pass\n"],
    ]
