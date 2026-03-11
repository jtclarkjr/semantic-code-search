mod api;
mod bundle;
mod chunking;
mod cli;
mod config;
mod file_types;
mod repo_scan;

pub async fn run<I, T>(args: I) -> anyhow::Result<()>
where
    I: IntoIterator<Item = T>,
    T: Into<std::ffi::OsString> + Clone,
{
    cli::run(args).await
}
