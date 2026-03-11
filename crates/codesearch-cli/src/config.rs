use anyhow::{anyhow, Context, Result};
use directories::ProjectDirs;
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct StoredConfig {
    pub api_base_url: String,
    pub supabase_url: Option<String>,
    pub supabase_publishable_key: Option<String>,
    pub supabase_storage_bucket: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredSession {
    pub access_token: String,
    pub refresh_token: Option<String>,
    pub expires_at: Option<i64>,
    pub token_type: String,
    pub user: Value,
}

#[derive(Debug, Clone)]
pub struct AppPaths {
    config_file: PathBuf,
    session_file: PathBuf,
}

impl AppPaths {
    pub fn new() -> Result<Self> {
        let project_dirs = ProjectDirs::from("dev", "semantic-code-search", "codesearch")
            .ok_or_else(|| anyhow!("failed to resolve application directories for codesearch"))?;
        Ok(Self {
            config_file: project_dirs.config_dir().join("config.json"),
            session_file: project_dirs.data_local_dir().join("session.json"),
        })
    }

    #[cfg(test)]
    pub fn for_test(root: &Path) -> Self {
        Self {
            config_file: root.join("config").join("config.json"),
            session_file: root.join("state").join("session.json"),
        }
    }

    pub fn load_config(&self) -> Result<Option<StoredConfig>> {
        load_json::<StoredConfig>(&self.config_file)
    }

    pub fn save_config(&self, config: &StoredConfig) -> Result<()> {
        save_json(&self.config_file, config)
    }

    pub fn load_session(&self) -> Result<Option<StoredSession>> {
        load_json::<StoredSession>(&self.session_file)
    }

    pub fn require_config(&self) -> Result<StoredConfig> {
        self.load_config()?
            .ok_or_else(|| anyhow!("run `codesearch login` first to store API configuration"))
    }

    pub fn require_session(&self) -> Result<StoredSession> {
        self.load_session()?
            .ok_or_else(|| anyhow!("run `codesearch login` first to authenticate"))
    }

    pub fn save_session(&self, session: &StoredSession) -> Result<()> {
        save_json(&self.session_file, session)
    }
}

impl StoredConfig {
    pub fn upload_config(&self) -> Result<UploadConfig> {
        Ok(UploadConfig {
            supabase_url: self
                .supabase_url
                .clone()
                .ok_or_else(|| anyhow!("login did not return a Supabase URL"))?,
            supabase_publishable_key: self
                .supabase_publishable_key
                .clone()
                .ok_or_else(|| anyhow!("login did not return a Supabase publishable key"))?,
            supabase_storage_bucket: self
                .supabase_storage_bucket
                .clone()
                .unwrap_or_else(|| "repo-bundles".to_string()),
        })
    }
}

#[derive(Debug, Clone)]
pub struct UploadConfig {
    pub supabase_url: String,
    pub supabase_publishable_key: String,
    pub supabase_storage_bucket: String,
}

fn load_json<T>(path: &Path) -> Result<Option<T>>
where
    T: DeserializeOwned,
{
    if !path.exists() {
        return Ok(None);
    }
    let content =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    let value = serde_json::from_str(&content)
        .with_context(|| format!("failed to parse {}", path.display()))?;
    Ok(Some(value))
}

fn save_json<T>(path: &Path, value: &T) -> Result<()>
where
    T: Serialize,
{
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create {}", parent.display()))?;
    }
    let content = serde_json::to_string_pretty(value)?;
    fs::write(path, content).with_context(|| format!("failed to write {}", path.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    #[test]
    fn config_and_session_round_trip() {
        let temp = tempdir().expect("tempdir");
        let paths = AppPaths::for_test(temp.path());
        let config = StoredConfig {
            api_base_url: "http://localhost:8000".to_string(),
            supabase_url: Some("https://demo.supabase.co".to_string()),
            supabase_publishable_key: Some("sb_publishable_demo".to_string()),
            supabase_storage_bucket: Some("repo-bundles".to_string()),
        };
        let session = StoredSession {
            access_token: "token".to_string(),
            refresh_token: None,
            expires_at: Some(123),
            token_type: "bearer".to_string(),
            user: json!({"email": "dev@example.com"}),
        };

        paths.save_config(&config).expect("save config");
        paths.save_session(&session).expect("save session");

        assert_eq!(
            paths
                .load_config()
                .expect("load config")
                .expect("config")
                .api_base_url,
            "http://localhost:8000"
        );
        assert_eq!(
            paths
                .load_session()
                .expect("load session")
                .expect("session")
                .access_token,
            "token"
        );
    }
}
