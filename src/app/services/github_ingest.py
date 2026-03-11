from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from common.repo_scan import RepoScanner
from common.schemas import RepoBundle


class GitHubIngestionService:
    def __init__(
        self,
        repo_scanner: RepoScanner,
        github_token: Optional[str] = None,
        clone_depth: int = 50,
    ) -> None:
        self.repo_scanner = repo_scanner
        self.github_token = github_token
        self.clone_depth = clone_depth

    def fetch_bundle(
        self,
        repo_name: str,
        clone_url: str,
        default_branch: Optional[str] = None,
    ) -> RepoBundle:
        with tempfile.TemporaryDirectory(prefix="semantic-code-search-") as temp_dir:
            target = Path(temp_dir) / "repo"
            command = ["git", "clone", f"--depth={self.clone_depth}"]
            if default_branch:
                command.extend(["--branch", default_branch])
            command.extend([self._authenticated_url(clone_url), str(target)])
            subprocess.run(command, check=True, capture_output=True, text=True)
            return self.repo_scanner.scan_path(
                target,
                repo_name=repo_name,
                source_type="github",
                source_ref=clone_url,
                default_branch=default_branch,
            )

    def _authenticated_url(self, clone_url: str) -> str:
        if not self.github_token or not clone_url.startswith("https://"):
            return clone_url
        prefix = "https://"
        return f"{prefix}x-access-token:{self.github_token}@{clone_url[len(prefix) :]}"
