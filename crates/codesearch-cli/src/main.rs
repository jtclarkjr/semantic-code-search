#[tokio::main]
async fn main() {
    if let Err(error) = codesearch::run(std::env::args_os()).await {
        eprintln!("error: {error:#}");
        std::process::exit(1);
    }
}
