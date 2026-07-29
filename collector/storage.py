from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from collector.util import (date_parts, format_utc, hour_parts, parse_utc,
                            read_jsonl_gzip, write_json_atomic,
                            write_jsonl_gzip_atomic)


@dataclass(frozen=True)
class TaskBucket:
    task_type: str
    due_hour: datetime
    task_directory: Path
    result_directory: Path


class DataStore:
    def __init__(self, root: Path, run_id: str | None = None):
        self.root = root
        self.run_id = run_id or uuid.uuid4().hex

    def initialize(self) -> None:
        for directory in (
            "records/selections",
            "records/owners",
            "records/results",
            "records/attempts",
            "tasks",
            "health",
            "state",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)

    def get_watermark(self) -> datetime | None:
        path = self.root / "state/watermark.json"
        if not path.exists():
            return None

        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("last_completed_gharchive_hour") is None:
            return None
        return parse_utc(value["last_completed_gharchive_hour"])

    def set_watermark(self, hour: datetime) -> None:
        write_json_atomic(
            self.root / "state/watermark.json",
            {
                "schema_version": 1,
                "last_completed_gharchive_hour": format_utc(hour),
            },
        )

    def selected_repository_ids(self) -> set[int]:
        result: set[int] = set()
        base = self.root / "records/selections"
        if not base.exists():
            return result

        for path in base.rglob("*.jsonl.gz"):
            for record in read_jsonl_gzip(path):
                repository_id = record.get("repository_id")
                if isinstance(repository_id, int):
                    result.add(repository_id)
        return result

    def owner_cache(self) -> dict[int, dict]:
        result: dict[int, dict] = {}
        base = self.root / "records/owners"
        if not base.exists():
            return result

        for path in base.rglob("*.jsonl.gz"):
            for record in read_jsonl_gzip(path):
                owner_id = record.get("owner_id")
                if isinstance(owner_id, int):
                    previous = result.get(owner_id)
                    if previous is None or record.get("observed_at", "") > previous.get(
                        "observed_at", ""
                    ):
                        result[owner_id] = record
        return result

    def write_selection_records(
        self,
        records: list[dict],
        timestamp: datetime,
    ) -> int:
        return self._write_dated_shard(
            "records/selections", records, timestamp
        )

    def write_owner_records(
        self,
        records: list[dict],
        timestamp: datetime,
    ) -> int:
        return self._write_dated_shard("records/owners", records, timestamp)

    def write_attempt_records(
        self,
        records: list[dict],
        timestamp: datetime,
    ) -> int:
        return self._write_dated_shard("records/attempts", records, timestamp)

    def write_health_report(self, report: dict, timestamp: datetime) -> None:
        year, month, day = date_parts(timestamp)
        path = (
            self.root
            / "health"
            / year
            / month
            / day
            / f"{self.run_id}.json"
        )
        write_json_atomic(path, report)

    def write_tasks(self, records: Iterable[dict]) -> int:
        grouped: dict[tuple[str, datetime], list[dict]] = {}

        for record in records:
            task_type = record["task_type"]
            due_at = parse_utc(record["due_at"])
            due_hour = due_at.replace(minute=0, second=0, microsecond=0)
            grouped.setdefault((task_type, due_hour), []).append(record)

        count = 0

        for (task_type, due_hour), group in grouped.items():
            parts = hour_parts(due_hour)
            directory = self.root / "tasks" / task_type
            for part in parts:
                directory /= part

            result_directory = self.root / "records/results" / task_type
            for part in parts:
                result_directory /= part

            complete_marker = result_directory / "_COMPLETE.json"
            complete_marker.unlink(missing_ok=True)

            path = directory / f"{self.run_id}.jsonl.gz"
            count += write_jsonl_gzip_atomic(path, group)

        return count

    def due_task_buckets(self, now: datetime) -> list[TaskBucket]:
        base = self.root / "tasks"
        if not base.exists():
            return []

        buckets: dict[tuple[str, str, str, str, str], TaskBucket] = {}

        for shard in base.rglob("*.jsonl.gz"):
            relative = shard.relative_to(base)
            parts = relative.parts

            if len(parts) < 6:
                continue

            task_type, year, month, day, hour = parts[:5]
            due_hour = parse_utc(
                f"{year}-{month}-{day}T{hour}:00:00Z"
            )
            if due_hour > now:
                continue

            task_directory = base / task_type / year / month / day / hour
            result_directory = (
                self.root
                / "records/results"
                / task_type
                / year
                / month
                / day
                / hour
            )

            if (result_directory / "_COMPLETE.json").exists():
                continue

            key = (task_type, year, month, day, hour)
            buckets[key] = TaskBucket(
                task_type=task_type,
                due_hour=due_hour,
                task_directory=task_directory,
                result_directory=result_directory,
            )

        return sorted(
            buckets.values(),
            key=lambda item: (item.due_hour, item.task_type),
        )

    @staticmethod
    def read_bucket_tasks(bucket: TaskBucket) -> dict[str, dict]:
        tasks: dict[str, dict] = {}
        for path in bucket.task_directory.glob("*.jsonl.gz"):
            for task in read_jsonl_gzip(path):
                tasks[task["task_id"]] = task
        return tasks

    @staticmethod
    def terminal_task_ids(bucket: TaskBucket) -> set[str]:
        result: set[str] = set()

        if not bucket.result_directory.exists():
            return result

        for path in bucket.result_directory.glob("*.jsonl.gz"):
            for record in read_jsonl_gzip(path):
                task_id = record.get("task_id")
                if task_id:
                    result.add(task_id)

        return result

    def write_bucket_results(
        self,
        bucket: TaskBucket,
        records: list[dict],
    ) -> int:
        if not records:
            return 0

        path = bucket.result_directory / f"{self.run_id}.jsonl.gz"
        return write_jsonl_gzip_atomic(path, records)

    def mark_bucket_complete(
        self,
        bucket: TaskBucket,
        completed_at: datetime,
        task_count: int,
    ) -> None:
        write_json_atomic(
            bucket.result_directory / "_COMPLETE.json",
            {
                "schema_version": 1,
                "task_type": bucket.task_type,
                "due_hour": format_utc(bucket.due_hour),
                "completed_at": format_utc(completed_at),
                "task_count": task_count,
            },
        )

    def _write_dated_shard(
        self,
        relative_base: str,
        records: list[dict],
        timestamp: datetime,
    ) -> int:
        if not records:
            return 0

        year, month, day = date_parts(timestamp)
        path = (
            self.root
            / relative_base
            / year
            / month
            / day
            / f"{self.run_id}.jsonl.gz"
        )
        return write_jsonl_gzip_atomic(path, records)


def initialize_local_data_repo(path: Path, first_hour: datetime) -> None:
    path.mkdir(parents=True, exist_ok=True)
    store = DataStore(path)
    store.initialize()

    write_json_atomic(
        path / "state/watermark.json",
        {
            "schema_version": 1,
            "last_completed_gharchive_hour": None,
            "configured_first_hour": format_utc(first_hour),
        },
    )

    readme = path / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Private prospective collection data\n\n"
            "This repository contains private, append-oriented collection data.\n",
            encoding="utf-8",
        )


class GitDataRepository:
    def __init__(
        self,
        url: str,
        token: str,
        branch: str,
    ):
        self.url = url
        self.token = token
        self.branch = branch

    def transaction(self):
        return _GitTransaction(self)


class _GitTransaction:
    def __init__(self, repository: GitDataRepository):
        self.repository = repository
        self.temporary_directory: tempfile.TemporaryDirectory | None = None
        self.root: Path | None = None
        self.environment: dict[str, str] | None = None

    def __enter__(self) -> Path:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="collector-data-"
        )
        base = Path(self.temporary_directory.name)
        self.root = base / "data"
        self.environment = self._git_environment(base)

        self._git(
            "clone",
            "--branch",
            self.repository.branch,
            "--single-branch",
            self.repository.url,
            str(self.root),
            cwd=base,
        )
        self._git(
            "config",
            "user.name",
            "prospective-collector",
            cwd=self.root,
        )
        self._git(
            "config",
            "user.email",
            "collector@users.noreply.github.com",
            cwd=self.root,
        )

        return self.root

    def __exit__(self, exception_type, exception, traceback) -> bool:
        try:
            if exception_type is not None:
                return False

            assert self.root is not None
            status = self._git(
                "status",
                "--porcelain",
                cwd=self.root,
                capture=True,
            )

            if not status.stdout.strip():
                return False

            self._git("add", "--all", cwd=self.root)
            self._git(
                "commit",
                "-m",
                "Collect prospective repository data",
                cwd=self.root,
            )
            self._git(
                "push",
                "origin",
                f"HEAD:{self.repository.branch}",
                cwd=self.root,
            )
            return False
        finally:
            if self.temporary_directory is not None:
                self.temporary_directory.cleanup()

    def _git_environment(self, base: Path) -> dict[str, str]:
        askpass = base / "git-askpass.py"
        askpass.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "prompt = ' '.join(sys.argv[1:]).lower()\n"
            "if 'username' in prompt:\n"
            "    print('x-access-token')\n"
            "else:\n"
            "    print(os.environ['COLLECTOR_DATA_TOKEN'])\n",
            encoding="utf-8",
        )
        askpass.chmod(askpass.stat().st_mode | stat.S_IXUSR)

        environment = os.environ.copy()
        environment.update(
            {
                "GIT_ASKPASS": str(askpass),
                "GIT_TERMINAL_PROMPT": "0",
                "COLLECTOR_DATA_TOKEN": self.repository.token,
            }
        )
        return environment

    def _git(
        self,
        *arguments: str,
        cwd: Path,
        capture: bool = False,
    ) -> subprocess.CompletedProcess:
        assert self.environment is not None
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            env=self.environment,
            check=True,
            text=True,
            capture_output=capture,
        )
