# Repo Bundle Contract

The local ingest CLI uploads a gzip-compressed JSON document to Supabase Storage.

## Encoding

- Content-Type: `application/gzip`
- Body: gzip-compressed UTF-8 JSON
- JSON top-level type: object matching `RepoBundle`

## Enums

- `source_type`: `github` | `local`
- `kind` / `document_kind`: `code` | `documentation` | `commit`

## Line numbering

- `start_line` and `end_line` are 1-based and inclusive.
- When a document is not chunked further, the first chunk starts at `1` and ends at the document line count.
- Oversized chunks keep overlapping content, but reported lines still describe the chunk slice in the original document.

## Required top-level fields

- `repo_name`
- `source_type`
- `source_ref`
- `metadata`
- `documents`
- `chunks`

See [`repo_bundle.schema.json`](/Users/jamesclark/GitHub/semantic-code-search/contracts/repo_bundle.schema.json) for the wire schema.

