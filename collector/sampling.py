from __future__ import annotations

import hashlib
import hmac


def _digest(key: bytes, domain: str, value: str) -> bytes:
    message = f"{domain}:{value}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).digest()


def sample_value(repository_id: int, key: bytes) -> float:
    digest = _digest(key, "sample", str(repository_id))
    integer = int.from_bytes(digest[:8], "big")
    return integer / 2**64


def is_selected(
    repository_id: int,
    key: bytes,
    probability: float,
) -> bool:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    return sample_value(repository_id, key) < probability


def sample_id(repository_id: int, key: bytes) -> str:
    return _digest(key, "sample-id", str(repository_id)).hex()[:32]


def owner_group_key(owner_id: int, key: bytes) -> str:
    return _digest(key, "owner-group", str(owner_id)).hex()[:32]
