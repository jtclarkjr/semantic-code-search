# Semantic Code Search

Semantic code search backend built with FastAPI, Supabase, pgvector, and a PyTorch embedding model. The repo ships two entrypoints:

- `semantic-code-search-api` for the FastAPI service
- `codesearch` as the Rust CLI installed from `crates/codesearch-cli`

## What it does

- Indexes code, documentation, and commit messages
- Stores embeddings in Supabase Postgres with pgvector
- Searches by meaning through a Supabase RPC
- Supports GitHub repo sync and local repo ingestion bundles

## Project layout

- `src/app`: FastAPI app, auth, background jobs, Supabase repository layer
- `src/common`: shared chunking, repo scanning, and bundle formats
- `crates/codesearch-cli`: Rust CLI for local login, ingest, job status, and search
- `sql/migrations`: pgvector schema and RPCs
- `tests`: unit and integration coverage

## Quick start

1. Copy `.env.example` to `.env` and fill in your Supabase credentials.
2. Apply the SQL migrations to your Supabase project:

```sql
\i sql/migrations/001_init.sql
\i sql/migrations/002_local_repo_identity.sql
```
3. Install dependencies:

```bash
uv sync --extra dev
```

4. Run the API:

```bash
uv run semantic-code-search-api
```

5. Install the Rust CLI:

```bash
cargo install --path crates/codesearch-cli --locked
```

6. Use the CLI:

```bash
codesearch login
codesearch ingest .
codesearch search "debounce function for Vue"
```

## Ingesting a local repo

1. Start the API locally:

```bash
uv run semantic-code-search-api
```

2. Log in once from the CLI:

```bash
codesearch login
```

The prompt asks for your FastAPI base URL, not your Supabase project URL. For local development that is usually `http://localhost:8000`.

3. Ingest the repo from its root:

```bash
codesearch ingest .
```

You can override the displayed repo name if needed:

```bash
codesearch ingest . --name react-frontend
```

### Local repo identity rules

- Local ingests are keyed by `user + absolute path + branch`.
- Re-ingesting the same local path on the same branch updates the existing repo snapshot instead of creating another repo entry.
- Ingesting the same local path on a different branch creates a separate repo entry for that branch.
- The branch value comes from the current git checkout discovered by the local scanner.

### What gets skipped

- Build and generated output is ignored during local ingest.
- Common frontend artifacts such as `storybook-static`, `*.bundle.js`, `*.iframe.bundle.js`, `manager-bundle.*`, and `*.chunk.js` are excluded so they do not pollute search results.

### After re-ingest

- Run `codesearch ingest .` again whenever you want to refresh the indexed snapshot for the current branch.
- Search uses the latest indexed snapshot for that repo identity.

## Runtime notes

- `SCS_USE_STUB_EMBEDDINGS=true` gives deterministic local embeddings without downloading a Hugging Face model. Turn it off in real deployments.
- Supabase handles auth, storage, and data access. The FastAPI process still runs separately from Supabase.
- Auth verification uses Supabase JWKS for the current asymmetric signing key (`ECC P-256` / `ES256`), not the legacy HS256 shared secret.
- Use Supabase `sb_publishable_...` and `sb_secret_...` API keys, not legacy `anon` / `service_role` keys.
- The backend login response includes the public Supabase upload settings the Rust CLI needs, so `codesearch` only has to ask for the API base URL once.
- The migration enables RLS for a shared authenticated workspace.
