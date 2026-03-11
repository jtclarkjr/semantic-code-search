use crate::api::{upload_bundle, ApiClient, SearchRequest};
use crate::bundle::bundle_to_gzip_bytes;
use crate::config::{AppPaths, StoredSession};
use crate::repo_scan::{default_repo_name, RepoScanner};
use anyhow::{anyhow, Result};
use chrono::Utc;
use clap::{Args, Parser, Subcommand};
use dialoguer::{Input, Password};
use std::ffi::OsString;
use std::path::PathBuf;

#[derive(Debug, Parser)]
#[command(name = "codesearch", version, about = "Semantic code search CLI")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    Login(LoginArgs),
    Ingest(IngestArgs),
    Job(JobArgs),
    Search(SearchArgs),
}

#[derive(Debug, Args)]
struct LoginArgs {
    #[arg(long)]
    api_base_url: Option<String>,
}

#[derive(Debug, Args)]
struct IngestArgs {
    #[arg(default_value = ".")]
    path: PathBuf,
    #[arg(long)]
    name: Option<String>,
}

#[derive(Debug, Args)]
struct JobArgs {
    job_id: String,
}

#[derive(Debug, Args)]
struct SearchArgs {
    #[arg(required = true)]
    query: Vec<String>,
    #[arg(long)]
    repo_id: Vec<String>,
    #[arg(long)]
    language: Vec<String>,
    #[arg(long = "content-type")]
    content_type: Vec<String>,
    #[arg(long, default_value_t = 10)]
    limit: u32,
}

pub async fn run<I, T>(args: I) -> Result<()>
where
    I: IntoIterator<Item = T>,
    T: Into<OsString> + Clone,
{
    let args = rewrite_search_shorthand(args);
    let cli = Cli::parse_from(args);
    match cli.command {
        Commands::Login(args) => login(args).await,
        Commands::Ingest(args) => ingest(args).await,
        Commands::Job(args) => job(args).await,
        Commands::Search(args) => search(args).await,
    }
}

async fn login(args: LoginArgs) -> Result<()> {
    let paths = AppPaths::new()?;
    let existing = paths.load_config()?;
    let current_url = args
        .api_base_url
        .or_else(|| existing.as_ref().map(|config| config.api_base_url.clone()))
        .unwrap_or_else(|| "http://localhost:8000".to_string());

    let api_base_url: String = Input::new()
        .with_prompt("API base URL")
        .default(current_url)
        .interact_text()?;
    let email: String = Input::new().with_prompt("Email").interact_text()?;
    let password = Password::new().with_prompt("Password").interact()?;

    let client = ApiClient::new(api_base_url.clone());
    let response = client.login(&email, &password).await?;

    let mut config = existing.unwrap_or_default();
    config.api_base_url = api_base_url;
    if let Some(public_config) = response.public_config.clone() {
        config.supabase_url = Some(public_config.supabase_url);
        config.supabase_publishable_key = Some(public_config.supabase_publishable_key);
        config.supabase_storage_bucket = Some(public_config.supabase_storage_bucket);
    }
    let session = StoredSession {
        access_token: response.access_token,
        refresh_token: response.refresh_token,
        expires_at: response.expires_at,
        token_type: response.token_type,
        user: response.user,
    };

    paths.save_config(&config)?;
    paths.save_session(&session)?;
    println!("Logged in. Stored config for {}", config.api_base_url);
    Ok(())
}

async fn ingest(args: IngestArgs) -> Result<()> {
    let paths = AppPaths::new()?;
    let config = paths.require_config()?;
    let session = paths.require_session()?;
    let upload_config = config.upload_config()?;

    let repo_path = args
        .path
        .canonicalize()
        .map_err(|error| anyhow!("failed to resolve {}: {error}", args.path.display()))?;
    let repo_name = args.name.unwrap_or_else(|| default_repo_name(&repo_path));
    let scanner = RepoScanner::default();
    let bundle = scanner.scan_path(&repo_path, &repo_name)?;
    let payload = bundle_to_gzip_bytes(&bundle)?;
    let object_path = format!(
        "local/{}-{}.json.gz",
        slugify(&repo_name),
        Utc::now().format("%Y%m%d%H%M%S")
    );

    upload_bundle(&upload_config, &session.access_token, &object_path, payload).await?;
    let client = ApiClient::new(config.api_base_url);
    let response = client
        .create_local_repository(
            &session.access_token,
            &repo_name,
            &object_path,
            &repo_path.to_string_lossy(),
            bundle.default_branch.as_deref(),
        )
        .await?;

    println!(
        "Queued local ingest job {} for repo {}",
        response.job.id, response.repository.name
    );
    Ok(())
}

async fn job(args: JobArgs) -> Result<()> {
    let paths = AppPaths::new()?;
    let config = paths.require_config()?;
    let session = paths.require_session()?;
    let client = ApiClient::new(config.api_base_url);
    let job = client.get_job(&session.access_token, &args.job_id).await?;
    println!("{}", serde_json::to_string_pretty(&job)?);
    Ok(())
}

async fn search(args: SearchArgs) -> Result<()> {
    let paths = AppPaths::new()?;
    let config = paths.require_config()?;
    let session = paths.require_session()?;
    let client = ApiClient::new(config.api_base_url);
    let response = client
        .search(
            &session.access_token,
            &SearchRequest {
                query: args.query.join(" "),
                repo_ids: optional_vec(args.repo_id),
                languages: optional_vec(args.language),
                content_types: optional_vec(args.content_type),
                limit: args.limit,
            },
        )
        .await?;

    if response.results.is_empty() {
        println!("No results.");
        return Ok(());
    }

    for result in response.results {
        let repo_name = result.repo_name.unwrap_or_else(|| result.repo_id.clone());
        println!(
            "[{:.3}] {} {}:{}-{}",
            result.score, repo_name, result.path, result.start_line, result.end_line
        );
        println!("{}", result.preview);
        println!();
    }
    Ok(())
}

fn optional_vec(values: Vec<String>) -> Option<Vec<String>> {
    if values.is_empty() {
        None
    } else {
        Some(values)
    }
}

fn slugify(value: &str) -> String {
    let mut slug = String::new();
    let mut last_dash = false;
    for character in value.chars() {
        let lowered = character.to_ascii_lowercase();
        if lowered.is_ascii_alphanumeric() {
            slug.push(lowered);
            last_dash = false;
        } else if !last_dash {
            slug.push('-');
            last_dash = true;
        }
    }
    slug.trim_matches('-').to_string()
}

fn rewrite_search_shorthand<I, T>(args: I) -> Vec<OsString>
where
    I: IntoIterator<Item = T>,
    T: Into<OsString> + Clone,
{
    let mut args: Vec<OsString> = args.into_iter().map(Into::into).collect();
    if args.len() <= 1 {
        return args;
    }

    let first = args[1].to_string_lossy().to_string();
    let known_commands = ["login", "ingest", "job", "search", "help", "--help", "-h"];
    if first.starts_with('-') || known_commands.iter().any(|command| *command == first) {
        return args;
    }

    args.insert(1, OsString::from("search"));
    args
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsString;

    #[test]
    fn rewrites_top_level_query_to_search_command() {
        let args = vec![
            OsString::from("codesearch"),
            OsString::from("debounce"),
            OsString::from("vue"),
        ];

        let rewritten = rewrite_search_shorthand(args);

        assert_eq!(rewritten[1], OsString::from("search"));
        assert_eq!(rewritten[2], OsString::from("debounce"));
        assert_eq!(rewritten[3], OsString::from("vue"));
    }

    #[test]
    fn leaves_known_subcommands_unchanged() {
        let args = vec![OsString::from("codesearch"), OsString::from("login")];
        let rewritten = rewrite_search_shorthand(args.clone());
        assert_eq!(rewritten, args);
    }

    #[test]
    fn slugify_replaces_non_alphanumeric_runs() {
        assert_eq!(slugify("My Repo Name"), "my-repo-name");
    }
}
