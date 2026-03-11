from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from common.chunking import ChunkingService
from common.file_types import (
    detect_language,
    is_code_path,
    is_documentation_path,
    is_generated_artifact_path,
    is_ignored_path,
    is_probably_text,
)
from common.schemas import RepoBundle, SourceDocument, SourceType


class RepoScanner:
    def __init__(
        self,
        chunking_service: Optional[ChunkingService] = None,
        max_file_bytes: int = 200_000,
        max_commit_messages: int = 200,
    ) -> None:
        self.chunking_service = chunking_service or ChunkingService()
        self.max_file_bytes = max_file_bytes
        self.max_commit_messages = max_commit_messages

    def scan_path(
        self,
        root: Path,
        repo_name: str,
        source_type: SourceType,
        source_ref: str,
        default_branch: Optional[str] = None,
    ) -> RepoBundle:
        root = root.resolve()
        documents = self._scan_files(root)
        latest_commit_sha = self._git_output(root, ["rev-parse", "HEAD"])
        documents.extend(self._scan_commit_messages(root))
        chunks = self.chunking_service.chunk_documents(documents)
        return RepoBundle(
            repo_name=repo_name,
            source_type=source_type,
            source_ref=source_ref,
            default_branch=default_branch
            or self._git_output(root, ["rev-parse", "--abbrev-ref", "HEAD"]),
            latest_commit_sha=latest_commit_sha or None,
            metadata={"root_name": root.name},
            documents=documents,
            chunks=chunks,
        )

    def _scan_files(self, root: Path) -> List[SourceDocument]:
        documents: List[SourceDocument] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if is_ignored_path(relative):
                continue
            relative_str = relative.as_posix()
            if is_generated_artifact_path(relative_str):
                continue
            if not is_probably_text(str(relative)):
                continue
            if path.stat().st_size > self.max_file_bytes:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(encoding="utf-8", errors="ignore")
            if not content.strip():
                continue

            if is_code_path(relative_str):
                kind = "code"
            elif is_documentation_path(relative_str):
                kind = "documentation"
            else:
                continue

            documents.append(
                SourceDocument(
                    kind=kind,
                    path=relative_str,
                    content=content,
                    title=relative.name,
                    language=detect_language(relative_str),
                    metadata={"size_bytes": path.stat().st_size},
                )
            )
        return documents

    def _scan_commit_messages(self, root: Path) -> List[SourceDocument]:
        raw = self._git_output(
            root,
            ["log", f"-n{self.max_commit_messages}", "--pretty=format:%H%x1f%s%x1f%b%x1e"],
        )
        if not raw:
            return []
        documents: List[SourceDocument] = []
        for item in raw.split("\x1e"):
            if not item.strip():
                continue
            sha, subject, body = (item.split("\x1f") + ["", ""])[:3]
            content = subject.strip()
            if body.strip():
                content = f"{content}\n\n{body.strip()}"
            documents.append(
                SourceDocument(
                    kind="commit",
                    path=f".git/commits/{sha[:12]}.txt",
                    content=content,
                    title=subject.strip()[:120],
                    language=None,
                    external_id=sha,
                    commit_sha=sha,
                    metadata={"kind": "commit_message"},
                )
            )
        return documents

    def _git_output(self, root: Path, args: List[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""
        return result.stdout.strip()
