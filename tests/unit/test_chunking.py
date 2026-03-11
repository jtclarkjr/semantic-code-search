from common.file_types import is_generated_artifact_path
from common.bundle import bundle_from_bytes, bundle_to_bytes
from common.chunking import ChunkingService
from common.schemas import RepoBundle, SourceDocument


def test_chunking_splits_python_functions() -> None:
    service = ChunkingService(max_chars=500)
    document = SourceDocument(
        kind="code",
        path="utils.py",
        language="python",
        content=(
            "def alpha():\n"
            "    return 1\n\n"
            "class Beta:\n"
            "    pass\n\n"
            "async def gamma():\n"
            "    return 3\n"
        ),
    )

    chunks = service.chunk_document(document)

    assert len(chunks) >= 3
    assert any("def alpha" in chunk.content for chunk in chunks)
    assert any("class Beta" in chunk.content for chunk in chunks)
    assert any("async def gamma" in chunk.content for chunk in chunks)


def test_bundle_round_trip() -> None:
    bundle = RepoBundle(
        repo_name="demo",
        source_type="local",
        source_ref="/tmp/demo",
        documents=[
            SourceDocument(
                kind="documentation",
                path="README.md",
                language="markdown",
                content="Semantic search docs",
            )
        ],
        chunks=[],
    )

    payload = bundle_to_bytes(bundle)
    restored = bundle_from_bytes(payload)

    assert restored.repo_name == bundle.repo_name
    assert restored.documents[0].content == "Semantic search docs"


def test_generated_bundle_paths_are_ignored() -> None:
    assert is_generated_artifact_path("storybook-static/sb-addons/onboarding-3/manager-bundle.js")
    assert is_generated_artifact_path("storybook-static/472.94d95cfd.iframe.bundle.js")
    assert is_generated_artifact_path("assets/app.bundle.js")
    assert not is_generated_artifact_path("src/features/debounce.ts")
