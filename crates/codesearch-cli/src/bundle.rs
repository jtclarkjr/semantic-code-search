use flate2::write::GzEncoder;
use flate2::Compression;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::io::Write;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum SourceType {
    Github,
    Local,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DocumentKind {
    Code,
    Documentation,
    Commit,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceDocument {
    pub document_id: String,
    pub kind: DocumentKind,
    pub path: String,
    pub content: String,
    pub title: Option<String>,
    pub language: Option<String>,
    pub external_id: Option<String>,
    pub commit_sha: Option<String>,
    pub metadata: Map<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceChunk {
    pub chunk_id: String,
    pub document_id: String,
    pub kind: DocumentKind,
    pub path: String,
    pub content: String,
    pub preview: String,
    pub start_line: i32,
    pub end_line: i32,
    pub language: Option<String>,
    pub commit_sha: Option<String>,
    pub metadata: Map<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RepoBundle {
    pub repo_name: String,
    pub source_type: SourceType,
    pub source_ref: String,
    pub default_branch: Option<String>,
    pub latest_commit_sha: Option<String>,
    pub metadata: Map<String, Value>,
    pub documents: Vec<SourceDocument>,
    pub chunks: Vec<SourceChunk>,
}

impl SourceDocument {
    pub fn new(kind: DocumentKind, path: String, content: String) -> Self {
        Self {
            document_id: Uuid::new_v4().to_string(),
            kind,
            path,
            content,
            title: None,
            language: None,
            external_id: None,
            commit_sha: None,
            metadata: Map::new(),
        }
    }
}

impl SourceChunk {
    pub fn new(document_id: String, kind: DocumentKind, path: String, content: String) -> Self {
        Self {
            chunk_id: Uuid::new_v4().to_string(),
            document_id,
            kind,
            path,
            content,
            preview: String::new(),
            start_line: 1,
            end_line: 1,
            language: None,
            commit_sha: None,
            metadata: Map::new(),
        }
    }
}

pub fn bundle_to_gzip_bytes(bundle: &RepoBundle) -> anyhow::Result<Vec<u8>> {
    let json = serde_json::to_vec(bundle)?;
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(&json)?;
    Ok(encoder.finish()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundle_serializes_expected_top_level_fields() {
        let bundle = RepoBundle {
            repo_name: "demo".to_string(),
            source_type: SourceType::Local,
            source_ref: "/tmp/demo".to_string(),
            default_branch: None,
            latest_commit_sha: None,
            metadata: Map::new(),
            documents: vec![],
            chunks: vec![],
        };

        let value = serde_json::to_value(bundle).expect("bundle should serialize");

        assert_eq!(value["repo_name"], "demo");
        assert_eq!(value["source_type"], "local");
        assert!(value.get("documents").is_some());
        assert!(value.get("chunks").is_some());
    }
}
