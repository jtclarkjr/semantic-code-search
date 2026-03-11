from __future__ import annotations

import gzip

from common.schemas import RepoBundle


def bundle_to_bytes(bundle: RepoBundle) -> bytes:
    return gzip.compress(bundle.model_dump_json().encode("utf-8"))


def bundle_from_bytes(payload: bytes) -> RepoBundle:
    return RepoBundle.model_validate_json(gzip.decompress(payload))
