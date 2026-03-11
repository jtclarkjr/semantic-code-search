use crate::bundle::{DocumentKind, RepoBundle, SourceDocument, SourceType};
use crate::chunking::ChunkingService;
use crate::file_types::{
    detect_language, is_code_path, is_documentation_path, is_generated_artifact_path,
    is_ignored_path, is_probably_text,
};
use anyhow::{Context, Result};
use git2::{Oid, Repository};
use serde_json::{json, Map, Value};
use std::fs;
use std::path::{Path, PathBuf};
use walkdir::{DirEntry, WalkDir};

#[derive(Debug, Clone)]
pub struct RepoScanner {
    pub max_file_bytes: u64,
    pub max_commit_messages: usize,
    pub chunking_service: ChunkingService,
}

impl Default for RepoScanner {
    fn default() -> Self {
        Self {
            max_file_bytes: 200_000,
            max_commit_messages: 200,
            chunking_service: ChunkingService::default(),
        }
    }
}

impl RepoScanner {
    pub fn scan_path(&self, root: &Path, repo_name: &str) -> Result<RepoBundle> {
        let root = root.canonicalize().context("failed to resolve repo path")?;
        let repository = Repository::discover(&root).ok();
        let mut documents = self.scan_files(&root)?;
        documents.extend(self.scan_commit_messages(&repository));
        let chunks = self.chunking_service.chunk_documents(&documents);
        let mut metadata = Map::new();
        metadata.insert(
            "root_name".to_string(),
            Value::String(
                root.file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or("repo")
                    .to_string(),
            ),
        );

        Ok(RepoBundle {
            repo_name: repo_name.to_string(),
            source_type: SourceType::Local,
            source_ref: root.to_string_lossy().to_string(),
            default_branch: repository
                .as_ref()
                .and_then(|repo| repo.head().ok())
                .and_then(|head| head.shorthand().map(str::to_string)),
            latest_commit_sha: repository
                .as_ref()
                .and_then(|repo| repo.head().ok())
                .and_then(|head| head.target().map(|oid| oid.to_string())),
            metadata,
            documents,
            chunks,
        })
    }

    fn scan_files(&self, root: &Path) -> Result<Vec<SourceDocument>> {
        let mut documents = Vec::new();
        let walker = WalkDir::new(root)
            .into_iter()
            .filter_entry(|entry| should_visit(root, entry));

        for entry in walker {
            let entry = entry?;
            if !entry.file_type().is_file() {
                continue;
            }
            let relative = relative_path(root, entry.path())?;
            if is_generated_artifact_path(&relative) {
                continue;
            }
            if !is_probably_text(&relative) {
                continue;
            }
            let metadata = entry.metadata()?;
            if metadata.len() > self.max_file_bytes {
                continue;
            }
            let bytes = fs::read(entry.path())?;
            let content = String::from_utf8_lossy(&bytes).into_owned();
            if content.trim().is_empty() {
                continue;
            }

            let kind = if is_code_path(&relative) {
                DocumentKind::Code
            } else if is_documentation_path(&relative) {
                DocumentKind::Documentation
            } else {
                continue;
            };

            let mut document = SourceDocument::new(kind, relative.clone(), content);
            document.title = entry.file_name().to_str().map(str::to_string);
            document.language = detect_language(&relative).map(str::to_string);
            document
                .metadata
                .insert("size_bytes".to_string(), json!(metadata.len()));
            documents.push(document);
        }

        Ok(documents)
    }

    fn scan_commit_messages(&self, repository: &Option<Repository>) -> Vec<SourceDocument> {
        let Some(repository) = repository else {
            return Vec::new();
        };
        let mut revwalk = match repository.revwalk() {
            Ok(revwalk) => revwalk,
            Err(_) => return Vec::new(),
        };
        if revwalk.push_head().is_err() {
            return Vec::new();
        }

        revwalk
            .take(self.max_commit_messages)
            .filter_map(Result::ok)
            .filter_map(|oid| build_commit_document(repository, oid))
            .collect()
    }
}

fn should_visit(root: &Path, entry: &DirEntry) -> bool {
    if entry.path() == root {
        return true;
    }
    match entry.path().strip_prefix(root) {
        Ok(relative) => !is_ignored_path(relative),
        Err(_) => true,
    }
}

fn relative_path(root: &Path, path: &Path) -> Result<String> {
    let relative = path
        .strip_prefix(root)
        .with_context(|| format!("failed to strip prefix for {}", path.display()))?;
    Ok(path_to_unix(relative))
}

fn path_to_unix(path: &Path) -> String {
    path.components()
        .map(|component| component.as_os_str().to_string_lossy().to_string())
        .collect::<Vec<_>>()
        .join("/")
}

fn build_commit_document(repository: &Repository, oid: Oid) -> Option<SourceDocument> {
    let commit = repository.find_commit(oid).ok()?;
    let sha = commit.id().to_string();
    let subject = commit.summary().unwrap_or_default().trim().to_string();
    let body = commit.body().unwrap_or_default().trim().to_string();
    let mut content = subject.clone();
    if !body.is_empty() {
        content = format!("{subject}\n\n{body}");
    }

    let mut document = SourceDocument::new(
        DocumentKind::Commit,
        format!(".git/commits/{}.txt", &sha[..12]),
        content,
    );
    document.title = Some(subject.chars().take(120).collect());
    document.external_id = Some(sha.clone());
    document.commit_sha = Some(sha);
    document
        .metadata
        .insert("kind".to_string(), json!("commit_message"));
    Some(document)
}

pub fn default_repo_name(path: &Path) -> String {
    let path = if path.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        path.to_path_buf()
    };
    let canonical = path.canonicalize().unwrap_or(path);
    canonical
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("repo")
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use git2::{Repository, Signature};
    use tempfile::tempdir;

    #[test]
    fn default_name_comes_from_directory() {
        let temp = tempdir().expect("tempdir");
        let name = default_repo_name(temp.path());
        assert_eq!(name, temp.path().file_name().unwrap().to_string_lossy());
    }

    #[test]
    fn scanner_skips_ignored_directories() {
        let temp = tempdir().expect("tempdir");
        let src_dir = temp.path().join("src");
        let ignored_dir = temp.path().join("node_modules");
        fs::create_dir_all(&src_dir).expect("create src");
        fs::create_dir_all(&ignored_dir).expect("create ignored");
        fs::write(src_dir.join("main.py"), "def run():\n    pass\n").expect("write source");
        fs::write(ignored_dir.join("ignored.js"), "export const x = 1;").expect("write ignored");

        let scanner = RepoScanner::default();
        let bundle = scanner.scan_path(temp.path(), "demo").expect("bundle");

        assert!(bundle.documents.iter().any(|doc| doc.path == "src/main.py"));
        assert!(!bundle
            .documents
            .iter()
            .any(|doc| doc.path.contains("node_modules")));
    }

    #[test]
    fn scanner_collects_commit_messages() {
        let temp = tempdir().expect("tempdir");
        let repo = Repository::init(temp.path()).expect("repo");
        fs::write(temp.path().join("README.md"), "hello").expect("write readme");

        let mut index = repo.index().expect("index");
        index.add_path(Path::new("README.md")).expect("add path");
        index.write().expect("write index");
        let tree_oid = index.write_tree().expect("write tree");
        let tree = repo.find_tree(tree_oid).expect("find tree");
        let signature = Signature::now("Test", "test@example.com").expect("signature");
        repo.commit(
            Some("HEAD"),
            &signature,
            &signature,
            "Initial commit",
            &tree,
            &[],
        )
        .expect("commit");

        let scanner = RepoScanner::default();
        let bundle = scanner.scan_path(temp.path(), "demo").expect("bundle");

        assert!(bundle
            .documents
            .iter()
            .any(|document| document.kind == DocumentKind::Commit
                && document.content.contains("Initial commit")));
    }

    #[test]
    fn scanner_skips_generated_bundles() {
        let temp = tempdir().expect("tempdir");
        let storybook_dir = temp.path().join("storybook-static");
        fs::create_dir_all(&storybook_dir).expect("create storybook");
        fs::write(
            storybook_dir.join("manager-bundle.js"),
            "(()=>{var a=1;console.log(a)})();",
        )
        .expect("write bundle");
        fs::write(
            temp.path().join("src.ts"),
            "export const debounce = () => null;\n",
        )
        .expect("write source");

        let scanner = RepoScanner::default();
        let bundle = scanner.scan_path(temp.path(), "demo").expect("bundle");

        assert!(bundle.documents.iter().any(|doc| doc.path == "src.ts"));
        assert!(!bundle
            .documents
            .iter()
            .any(|doc| doc.path.contains("storybook-static")
                || doc.path.contains("manager-bundle.js")));
    }
}
