alter table public.repositories
    add column if not exists identity_key text;

update public.repositories
set identity_key = case
    when source_type = 'local' then concat(
        'local:',
        coalesce(created_by::text, 'shared'),
        ':',
        source_ref,
        ':',
        coalesce(default_branch, '__default__')
    )
    else concat(source_type, ':', source_ref)
end
where identity_key is null;

alter table public.repositories
    alter column identity_key set not null;

drop index if exists public.repositories_source_idx;

create unique index if not exists repositories_identity_idx
    on public.repositories (source_type, identity_key);

