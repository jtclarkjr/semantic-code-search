use std::path::Path;

pub const IGNORED_DIRECTORIES: &[&str] = &[
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
];

const GENERATED_BUNDLE_SUFFIXES: &[&str] = &[
    ".bundle.js",
    ".chunk.js",
    ".iframe.bundle.js",
    ".manager-bundle.js",
    ".min.js",
    ".min.css",
];

pub fn is_ignored_path(path: &Path) -> bool {
    path.components().any(|component| {
        let part = component.as_os_str().to_string_lossy();
        IGNORED_DIRECTORIES.iter().any(|ignored| *ignored == part)
    })
}

pub fn is_generated_artifact_path(path: &str) -> bool {
    let lowered = path.to_ascii_lowercase();
    let file_name = Path::new(path)
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    GENERATED_BUNDLE_SUFFIXES
        .iter()
        .any(|suffix| lowered.ends_with(suffix))
        || lowered.contains("storybook-static/")
        || file_name.starts_with("manager-bundle.")
}

pub fn detect_language(path: &str) -> Option<&'static str> {
    match Path::new(path)
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .as_deref()
    {
        Some("py") | Some("pyi") => Some("python"),
        Some("js") | Some("jsx") | Some("cjs") | Some("mjs") => Some("javascript"),
        Some("ts") | Some("tsx") => Some("typescript"),
        Some("vue") => Some("vue"),
        Some("md") | Some("mdx") => Some("markdown"),
        Some("rst") => Some("rst"),
        Some("txt") => Some("text"),
        Some("json") => Some("json"),
        Some("yml") | Some("yaml") => Some("yaml"),
        Some("toml") => Some("toml"),
        _ => None,
    }
}

pub fn is_documentation_path(path: &str) -> bool {
    let lowered = Path::new(path)
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    matches!(
        lowered.as_str(),
        "readme"
            | "readme.md"
            | "contributing.md"
            | "architecture.md"
            | "design.md"
            | "notes.md"
            | "changelog.md"
    ) || matches!(
        Path::new(path)
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.to_ascii_lowercase())
            .as_deref(),
        Some("md") | Some("mdx") | Some("rst") | Some("txt")
    )
}

pub fn is_code_path(path: &str) -> bool {
    matches!(
        detect_language(path),
        Some("python") | Some("javascript") | Some("typescript") | Some("vue")
    )
}

pub fn is_probably_text(path: &str) -> bool {
    matches!(
        Path::new(path)
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.to_ascii_lowercase())
            .as_deref(),
        Some("py")
            | Some("pyi")
            | Some("js")
            | Some("jsx")
            | Some("cjs")
            | Some("mjs")
            | Some("ts")
            | Some("tsx")
            | Some("vue")
            | Some("md")
            | Some("mdx")
            | Some("rst")
            | Some("txt")
            | Some("json")
            | Some("yml")
            | Some("yaml")
            | Some("toml")
            | Some("css")
            | Some("scss")
            | Some("html")
            | Some("sql")
            | Some("sh")
    ) || is_documentation_path(path)
}
