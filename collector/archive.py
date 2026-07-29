from __future__ import annotations

import gzip
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from collector.util import format_utc, parse_utc

GH_ARCHIVE_BASE = "https://data.gharchive.org"


@dataclass(frozen=True)
class CreationCandidate:
    event_id: str
    repository_id: int
    repository_name_at_discovery: str
    event_created_at: datetime
    gharchive_hour: datetime

    def as_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "repository_id": self.repository_id,
            "repository_name_at_discovery": self.repository_name_at_discovery,
            "event_created_at": format_utc(self.event_created_at),
            "gharchive_hour": format_utc(self.gharchive_hour),
        }


def archive_url(hour: datetime) -> str:
    filename = (
        f"{hour.year:04d}-{hour.month:02d}-{hour.day:02d}-{hour.hour}.json.gz"
    )
    return f"{GH_ARCHIVE_BASE}/{filename}"


def download_archive_hour(
    hour: datetime,
    destination: Path | None = None,
    attempts: int = 3,
) -> Path:
    if destination is None:
        directory = Path(tempfile.mkdtemp(prefix="gharchive-"))
        destination = directory / (
            f"{hour.year:04d}-{hour.month:02d}-{hour.day:02d}-{hour.hour}.json.gz"
        )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(
        archive_url(hour),
        headers={"User-Agent": "project-potential-collector/1.0"},
    )

    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
            return destination
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)

    raise RuntimeError(f"Unable to download {archive_url(hour)}") from last_error


def iter_repository_creations(
    path: Path,
    gharchive_hour: datetime | None = None,
):
    seen_repository_ids: set[int] = set()

    if gharchive_hour is None:
        gharchive_hour = _hour_from_filename(path.name)

    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "CreateEvent":
                continue

            payload = event.get("payload") or {}
            if payload.get("ref_type") != "repository":
                continue

            repository = event.get("repo") or {}
            repository_id = repository.get("id")

            if not isinstance(repository_id, int):
                continue
            if repository_id in seen_repository_ids:
                continue

            event_created_at = event.get("created_at")
            if not event_created_at:
                continue

            seen_repository_ids.add(repository_id)

            yield CreationCandidate(
                event_id=str(event.get("id", "")),
                repository_id=repository_id,
                repository_name_at_discovery=str(repository.get("name", "")),
                event_created_at=parse_utc(event_created_at),
                gharchive_hour=gharchive_hour,
            )


def inspect_archive(path: Path) -> dict:
    creations = list(iter_repository_creations(path))
    return {
        "path": str(path),
        "repository_create_events": len(creations),
        "first_event_at": (
            format_utc(min(item.event_created_at for item in creations))
            if creations
            else None
        ),
        "last_event_at": (
            format_utc(max(item.event_created_at for item in creations))
            if creations
            else None
        ),
    }


def _hour_from_filename(filename: str) -> datetime:
    stem = filename
    if stem.endswith(".json.gz"):
        stem = stem[:-8]

    date_part, hour_part = stem.rsplit("-", 1)
    return parse_utc(f"{date_part}T{int(hour_part):02d}:00:00Z")
