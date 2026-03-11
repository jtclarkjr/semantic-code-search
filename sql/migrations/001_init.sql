create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists public.repositories (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    source_type text not null check (source_type in ('github', 'local')),
    source_ref text not null,
    default_branch text,
    latest_commit_sha text,
    current_index_version integer not null default 0,
    metadata jsonb not null default '{}'::jsonb,
    created_by uuid references auth.users (id),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists repositories_source_idx
    on public.repositories (source_type, source_ref);

create table if not exists public.documents (
    id uuid primary key,
    repo_id uuid not null references public.repositories (id) on delete cascade,
    document_kind text not null check (document_kind in ('code', 'documentation', 'commit')),
    path text not null,
    language text,
    title text,
    external_id text,
    commit_sha text,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    index_version integer not null,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists documents_repo_version_idx
    on public.documents (repo_id, index_version);

create table if not exists public.chunks (
    id uuid primary key,
    repo_id uuid not null references public.repositories (id) on delete cascade,
    document_id uuid not null references public.documents (id) on delete cascade,
    document_kind text not null check (document_kind in ('code', 'documentation', 'commit')),
    path text not null,
    language text,
    preview text not null,
    content text not null,
    start_line integer not null default 1,
    end_line integer not null default 1,
    commit_sha text,
    metadata jsonb not null default '{}'::jsonb,
    index_version integer not null,
    embedding vector(768) not null,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists chunks_repo_version_idx
    on public.chunks (repo_id, index_version);
create index if not exists chunks_repo_language_idx
    on public.chunks (repo_id, language);
create index if not exists chunks_repo_kind_idx
    on public.chunks (repo_id, document_kind);
create index if not exists chunks_embedding_idx
    on public.chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

create table if not exists public.ingestion_jobs (
    id uuid primary key default gen_random_uuid(),
    repo_id uuid references public.repositories (id) on delete cascade,
    job_type text not null check (job_type in ('github_sync', 'local_bundle')),
    status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed')),
    payload jsonb not null default '{}'::jsonb,
    stats jsonb not null default '{}'::jsonb,
    error text,
    attempts integer not null default 0,
    worker_name text,
    locked_at timestamptz,
    created_by uuid references auth.users (id),
    completed_at timestamptz,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists ingestion_jobs_status_idx
    on public.ingestion_jobs (status, created_at);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists repositories_set_updated_at on public.repositories;
create trigger repositories_set_updated_at
before update on public.repositories
for each row
execute function public.set_updated_at();

drop trigger if exists ingestion_jobs_set_updated_at on public.ingestion_jobs;
create trigger ingestion_jobs_set_updated_at
before update on public.ingestion_jobs
for each row
execute function public.set_updated_at();

alter table public.repositories enable row level security;
alter table public.documents enable row level security;
alter table public.chunks enable row level security;
alter table public.ingestion_jobs enable row level security;

create policy "authenticated users can read repositories"
    on public.repositories
    for select
    to authenticated
    using (true);

create policy "authenticated users can read documents"
    on public.documents
    for select
    to authenticated
    using (true);

create policy "authenticated users can read chunks"
    on public.chunks
    for select
    to authenticated
    using (true);

create policy "authenticated users can read ingestion jobs"
    on public.ingestion_jobs
    for select
    to authenticated
    using (true);

create policy "authenticated users can enqueue repositories"
    on public.repositories
    for insert
    to authenticated
    with check (true);

create policy "authenticated users can enqueue jobs"
    on public.ingestion_jobs
    for insert
    to authenticated
    with check (true);

create policy "authenticated users can update repositories"
    on public.repositories
    for update
    to authenticated
    using (true)
    with check (true);

create policy "authenticated users can update ingestion jobs"
    on public.ingestion_jobs
    for update
    to authenticated
    using (true)
    with check (true);

create or replace function public.claim_ingestion_job(worker_name text default null)
returns setof public.ingestion_jobs
language plpgsql
security definer
as $$
declare
    claimed public.ingestion_jobs;
begin
    update public.ingestion_jobs
    set
        status = 'running',
        locked_at = timezone('utc', now()),
        worker_name = claim_ingestion_job.worker_name,
        attempts = attempts + 1
    where id = (
        select id
        from public.ingestion_jobs
        where status = 'pending'
        order by created_at asc
        limit 1
        for update skip locked
    )
    returning * into claimed;

    if claimed.id is null then
        return;
    end if;

    return query select claimed.*;
end;
$$;

grant execute on function public.claim_ingestion_job(text) to authenticated, service_role;

create or replace function public.match_chunks(
    query_embedding vector(768),
    match_count integer default 10,
    repo_ids uuid[] default null,
    languages text[] default null,
    document_kinds text[] default null
)
returns table (
    chunk_id uuid,
    repo_id uuid,
    repo_name text,
    document_id uuid,
    document_kind text,
    path text,
    language text,
    preview text,
    content text,
    start_line integer,
    end_line integer,
    commit_sha text,
    metadata jsonb,
    score double precision
)
language sql
stable
security invoker
as $$
    select
        c.id as chunk_id,
        c.repo_id,
        r.name as repo_name,
        c.document_id,
        c.document_kind,
        c.path,
        c.language,
        c.preview,
        c.content,
        c.start_line,
        c.end_line,
        c.commit_sha,
        c.metadata,
        1 - (c.embedding <=> query_embedding) as score
    from public.chunks c
    join public.repositories r on r.id = c.repo_id
    where c.index_version = r.current_index_version
      and (repo_ids is null or c.repo_id = any(repo_ids))
      and (languages is null or c.language = any(languages))
      and (document_kinds is null or c.document_kind = any(document_kinds))
    order by c.embedding <=> query_embedding
    limit greatest(match_count, 1);
$$;

grant execute on function public.match_chunks(vector(768), integer, uuid[], text[], text[])
    to authenticated, service_role;

insert into storage.buckets (id, name, public)
values ('repo-bundles', 'repo-bundles', false)
on conflict (id) do nothing;

create policy "authenticated users can upload repo bundles"
    on storage.objects
    for insert
    to authenticated
    with check (bucket_id = 'repo-bundles');

create policy "authenticated users can read repo bundles"
    on storage.objects
    for select
    to authenticated
    using (bucket_id = 'repo-bundles');
