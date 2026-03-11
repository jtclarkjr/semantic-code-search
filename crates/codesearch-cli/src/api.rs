use crate::config::UploadConfig;
use anyhow::{anyhow, bail, Context, Result};
use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use reqwest::{Client, Url};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone, Deserialize)]
pub struct PublicClientConfig {
    pub supabase_url: String,
    pub supabase_publishable_key: String,
    pub supabase_storage_bucket: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct LoginResponse {
    pub access_token: String,
    pub refresh_token: Option<String>,
    pub expires_at: Option<i64>,
    pub token_type: String,
    pub user: Value,
    pub public_config: Option<PublicClientConfig>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RepositoryResponse {
    pub id: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobResponse {
    pub id: String,
    pub repo_id: Option<String>,
    pub job_type: String,
    pub status: String,
    pub payload: Value,
    pub stats: Value,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RepositoryQueuedResponse {
    pub repository: RepositoryResponse,
    pub job: JobResponse,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub chunk_id: String,
    pub repo_id: String,
    pub repo_name: Option<String>,
    pub path: String,
    pub language: Option<String>,
    pub document_kind: String,
    pub preview: String,
    pub content: String,
    pub start_line: i32,
    pub end_line: i32,
    pub score: f64,
    pub commit_sha: Option<String>,
    pub metadata: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResponse {
    pub results: Vec<SearchResult>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SearchRequest {
    pub query: String,
    pub repo_ids: Option<Vec<String>>,
    pub languages: Option<Vec<String>>,
    pub content_types: Option<Vec<String>>,
    pub limit: u32,
}

#[derive(Debug, Clone)]
pub struct ApiClient {
    base_url: String,
    client: Client,
}

impl ApiClient {
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into().trim_end_matches('/').to_string(),
            client: Client::new(),
        }
    }

    pub async fn login(&self, email: &str, password: &str) -> Result<LoginResponse> {
        let response = self
            .client
            .post(self.url("/v1/auth/login")?)
            .json(&json!({
                "email": email,
                "password": password,
            }))
            .send()
            .await
            .context("failed to call login endpoint")?;
        parse_json(response).await
    }

    pub async fn create_local_repository(
        &self,
        access_token: &str,
        name: &str,
        bundle_object_path: &str,
        source_ref: &str,
        default_branch: Option<&str>,
    ) -> Result<RepositoryQueuedResponse> {
        let response = self
            .client
            .post(self.url("/v1/repos/local")?)
            .bearer_auth(access_token)
            .json(&json!({
                "name": name,
                "bundle_object_path": bundle_object_path,
                "source_ref": source_ref,
                "default_branch": default_branch,
                "metadata": {"ingested_from": "codesearch"},
            }))
            .send()
            .await
            .context("failed to enqueue local repository")?;
        parse_json(response).await
    }

    pub async fn get_job(&self, access_token: &str, job_id: &str) -> Result<JobResponse> {
        let response = self
            .client
            .get(self.url(&format!("/v1/jobs/{job_id}"))?)
            .bearer_auth(access_token)
            .send()
            .await
            .context("failed to fetch job status")?;
        parse_json(response).await
    }

    pub async fn search(
        &self,
        access_token: &str,
        request: &SearchRequest,
    ) -> Result<SearchResponse> {
        let response = self
            .client
            .post(self.url("/v1/search")?)
            .bearer_auth(access_token)
            .json(request)
            .send()
            .await
            .context("failed to call search endpoint")?;
        parse_json(response).await
    }

    fn url(&self, path: &str) -> Result<Url> {
        Url::parse(&format!("{}{}", self.base_url, path))
            .with_context(|| format!("invalid API base URL `{}`", self.base_url))
    }
}

pub async fn upload_bundle(
    config: &UploadConfig,
    access_token: &str,
    object_path: &str,
    payload: Vec<u8>,
) -> Result<()> {
    let client = Client::new();
    let mut url = Url::parse(&config.supabase_url)
        .with_context(|| format!("invalid Supabase URL `{}`", config.supabase_url))?;
    {
        let mut segments = url
            .path_segments_mut()
            .map_err(|_| anyhow!("Supabase URL cannot be used for storage uploads"))?;
        segments.extend(["storage", "v1", "object", &config.supabase_storage_bucket]);
        for segment in object_path.split('/') {
            if !segment.is_empty() {
                segments.push(segment);
            }
        }
    }

    let mut headers = HeaderMap::new();
    headers.insert(
        "apikey",
        HeaderValue::from_str(&config.supabase_publishable_key)
            .context("invalid publishable key header")?,
    );
    headers.insert(
        AUTHORIZATION,
        HeaderValue::from_str(&format!("Bearer {access_token}"))
            .context("invalid authorization header")?,
    );
    headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/gzip"));
    headers.insert("x-upsert", HeaderValue::from_static("true"));

    let response = client
        .post(url)
        .headers(headers)
        .body(payload)
        .send()
        .await
        .context("failed to upload bundle to Supabase Storage")?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        bail!("Supabase Storage upload failed with {status}: {body}");
    }

    Ok(())
}

async fn parse_json<T>(response: reqwest::Response) -> Result<T>
where
    T: for<'de> Deserialize<'de>,
{
    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        bail!("request failed with {status}: {body}");
    }
    Ok(response.json::<T>().await?)
}
