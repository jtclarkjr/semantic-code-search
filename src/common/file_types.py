from __future__ import annotations

from pathlib import Path
from typing import Optional

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".idea",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    "node_modules",
    "storybook-static",
    "dist",
    "build",
    "coverage",
    "__pycache__",
}

DOCUMENTATION_FILENAMES = {
    "readme",
    "readme.md",
    "contributing.md",
    "architecture.md",
    "design.md",
    "notes.md",
    "changelog.md",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cjs": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
}

TEXT_EXTENSIONS = set(LANGUAGE_BY_EXTENSION)
TEXT_EXTENSIONS.update({".css", ".scss", ".html", ".sql", ".sh"})

GENERATED_BUNDLE_SUFFIXES = {
    ".bundle.js",
    ".chunk.js",
    ".iframe.bundle.js",
    ".manager-bundle.js",
    ".min.js",
    ".min.css",
}


def is_ignored_path(path: Path) -> bool:
    return any(part in IGNORED_DIRECTORIES for part in path.parts)


def is_generated_artifact_path(path: str) -> bool:
    lowered = path.lower()
    file_name = Path(path).name.lower()
    return (
        any(lowered.endswith(suffix) for suffix in GENERATED_BUNDLE_SUFFIXES)
        or "storybook-static/" in lowered
        or file_name.startswith("manager-bundle.")
    )


def detect_language(path: str) -> Optional[str]:
    return LANGUAGE_BY_EXTENSION.get(Path(path).suffix.lower())


def is_documentation_path(path: str) -> bool:
    file_name = Path(path).name.lower()
    if file_name in DOCUMENTATION_FILENAMES:
        return True
    return Path(path).suffix.lower() in {".md", ".mdx", ".rst", ".txt"}


def is_code_path(path: str) -> bool:
    language = detect_language(path)
    return language in {"python", "javascript", "typescript", "vue"}


def is_probably_text(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS or is_documentation_path(path)
