from __future__ import annotations

from typing import Optional

from supabase import Client, create_client


def build_supabase_client(url: str, key: str, access_token: Optional[str] = None) -> Client:
    client = create_client(url, key)
    if access_token:
        _attach_access_token(client, access_token)
    return client


def _attach_access_token(client: Client, access_token: str) -> None:
    auth_header = f"Bearer {access_token}"
    postgrest = getattr(client, "postgrest", None)
    if postgrest is not None:
        headers = getattr(postgrest, "session", None)
        if hasattr(postgrest, "auth"):
            postgrest.auth(access_token)
        elif headers is not None and hasattr(headers, "headers"):
            headers.headers["Authorization"] = auth_header

    storage = getattr(client, "storage", None)
    if storage is not None and hasattr(storage, "headers"):
        storage.headers["Authorization"] = auth_header
