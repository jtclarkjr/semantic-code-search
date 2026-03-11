from __future__ import annotations

from typing import Any

from common.bundle import bundle_from_bytes
from common.schemas import RepoBundle


class LocalBundleService:
    def __init__(self, storage_client: Any, bucket_name: str) -> None:
        self.storage_client = storage_client
        self.bucket_name = bucket_name

    def fetch_bundle(self, object_path: str) -> RepoBundle:
        payload = self.storage_client.storage.from_(self.bucket_name).download(object_path)
        if isinstance(payload, tuple):
            payload = payload[0]
        return bundle_from_bytes(payload)
