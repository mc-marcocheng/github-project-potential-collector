from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tempfile
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    result = datetime.fromisoformat(normalized)
    if result.tzinfo is None:
        raise ValueError(f"Timestamp has no timezone: {value}")

    return result.astimezone(UTC)


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def floor_hour(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def hour_after(value: datetime) -> datetime:
    return floor_hour(value) + timedelta(hours=1)


def canonical_json(record: object) -> str:
    return json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    value = value.replace("\x00", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = unicodedata.normalize("NFKC", value)

    lines = [line.rstrip() for line in value.splitlines()]
    return "\n".join(lines).strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_jsonl_gzip(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8", errors="strict") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}") from exc


def write_jsonl_gzip_atomic(path: Path, records: Iterable[dict]) -> int:
    materialized = list(records)
    if not materialized:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)

    try:
        with temporary_path.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                fileobj=raw,
                mode="wb",
                mtime=0,
            ) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8") as text:
                    for record in materialized:
                        text.write(canonical_json(record))
                        text.write("\n")

        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return len(materialized)


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)

    try:
        temporary_path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def date_parts(value: datetime) -> tuple[str, str, str]:
    value = value.astimezone(UTC)
    return f"{value.year:04d}", f"{value.month:02d}", f"{value.day:02d}"


def hour_parts(value: datetime) -> tuple[str, str, str, str]:
    value = value.astimezone(UTC)
    return (
        f"{value.year:04d}",
        f"{value.month:02d}",
        f"{value.day:02d}",
        f"{value.hour:02d}",
    )
