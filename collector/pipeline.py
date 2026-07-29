from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collector.api import GitHubAPI, RateLimitDeferred
from collector.archive import download_archive_hour, iter_repository_launches
from collector.config import Config
from collector.sampling import is_selected, owner_group_key, sample_id
from collector.storage import DataStore, GitDataRepository, TaskBucket
from collector.util import (floor_hour, format_utc, normalize_text, parse_utc,
                            sha256_bytes, stable_sha256, utc_now)


@dataclass
class RunHealth:
    started_at: datetime
    counters: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    last_archive_hour_processed: str | None = None

    def report(
        self,
        finished_at: datetime,
        api_requests: int,
        watermark: datetime | None,
    ) -> dict:
        return {
            "schema_version": 1,
            "record_type": "health",
            "started_at": format_utc(self.started_at),
            "finished_at": format_utc(finished_at),
            "last_gharchive_hour_processed": self.last_archive_hour_processed,
            "watermark": format_utc(watermark) if watermark else None,
            "api_requests": api_requests,
            "counters": dict(sorted(self.counters.items())),
            "errors": self.errors[:50],
        }


@dataclass
class TaskOutcome:
    terminal_record: dict | None = None
    owner_record: dict | None = None
    retry_reason: str | None = None


def run_with_git_storage(config: Config) -> None:
    repository = GitDataRepository(
        url=config.data_repo_url,
        token=config.data_repo_token,
        branch=config.data_repo_branch,
    )

    last_error: Exception | None = None

    for attempt in range(config.git_retries):
        try:
            with repository.transaction() as root:
                report = run_collection(root, config)
                print(json.dumps(report, sort_keys=True))
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt + 1 < config.git_retries:
                time.sleep(2**attempt)
                continue
            raise

    if last_error:
        raise last_error


def run_collection(root: Path, config: Config) -> dict:
    now = utc_now()
    health = RunHealth(started_at=now)
    store = DataStore(root)
    store.initialize()

    api = GitHubAPI(
        token=config.github_api_token,
        rate_limit_reserve=config.api_rate_limit_reserve,
        max_sleep_seconds=config.api_max_sleep_seconds,
    )

    discover_repositories(store, config, health, now)
    execute_due_tasks(store, config, api, health, now)

    finished_at = utc_now()
    report = health.report(
        finished_at=finished_at,
        api_requests=api.requests_made,
        watermark=store.get_watermark(),
    )
    store.write_health_report(report, finished_at)
    return report


def discover_repositories(
    store: DataStore,
    config: Config,
    health: RunHealth,
    now: datetime,
) -> None:
    watermark = store.get_watermark()
    next_hour = config.start_hour if watermark is None else watermark + timedelta(hours=1)
    cutoff = floor_hour(now - timedelta(hours=config.safety_lag_hours))

    selected_ids = store.selected_repository_ids()
    processed_hours = 0

    while (
        next_hour <= cutoff
        and processed_hours < config.max_archive_hours_per_run
    ):
        try:
            archive_path = download_archive_hour(next_hour)
            candidates = list(
                iter_repository_launches(
                    archive_path,
                    gharchive_hour=next_hour,
                )
            )
        except Exception as exc:
            health.errors.append(
                f"gharchive_download_or_parse:{format_utc(next_hour)}:"
                f"{type(exc).__name__}"
            )
            health.counters["archive_hours_failed"] += 1
            break

        health.counters["archive_hours_processed"] += 1
        health.counters["repository_launch_events"] += len(candidates)

        selection_records: list[dict] = []
        task_records: list[dict] = []

        for candidate in candidates:
            if candidate.repository_id in selected_ids:
                health.counters["duplicate_repository_creations"] += 1
                continue

            if not is_selected(
                candidate.repository_id,
                config.sampling_key,
                config.sampling_probability,
            ):
                continue

            selected_ids.add(candidate.repository_id)
            identifier = sample_id(
                candidate.repository_id,
                config.sampling_key,
            )

            landmark = candidate.event_created_at + timedelta(hours=24)

            selection = {
                "schema_version": 1,
                "record_type": "selection",
                "protocol_version": config.protocol_version,
                "sample_id": identifier,
                "repository_id": candidate.repository_id,
                "owner_id": None,
                "event_id": candidate.event_id,
                "discovery_event_kind": candidate.discovery_event_kind,
                "repository_name_at_discovery": (
                    candidate.repository_name_at_discovery
                ),
                "event_created_at": format_utc(candidate.event_created_at),
                "launch_landmark_at": format_utc(landmark),
                "discovered_at": format_utc(now),
                "gharchive_hour": format_utc(candidate.gharchive_hour),
                "sampling_probability": config.sampling_probability,
            }
            selection_records.append(selection)
            task_records.extend(build_tasks(selection))

        store.write_selection_records(selection_records, next_hour)
        store.write_tasks(task_records)
        store.set_watermark(next_hour)

        health.counters["repositories_sampled"] += len(selection_records)
        health.counters["tasks_created"] += len(task_records)
        health.last_archive_hour_processed = format_utc(next_hour)

        processed_hours += 1
        next_hour += timedelta(hours=1)


def build_tasks(selection: dict) -> list[dict]:
    sample = selection["sample_id"]
    repository_id = selection["repository_id"]
    landmark = parse_utc(selection["launch_landmark_at"])

    specifications = [
        ("snapshot", landmark, None),
        ("stars-30d", landmark + timedelta(days=30), 30),
        ("stars-90d", landmark + timedelta(days=90), 90),
        ("stars-180d", landmark + timedelta(days=180), 180),
    ]

    result: list[dict] = []

    for task_type, due_at, horizon_days in specifications:
        logical_key = (
            f"{sample}:{task_type}:{format_utc(due_at)}"
        )
        result.append(
            {
                "schema_version": 1,
                "record_type": "task",
                "protocol_version": selection["protocol_version"],
                "task_id": stable_sha256(logical_key),
                "sample_id": sample,
                "repository_id": repository_id,
                "task_type": task_type,
                "horizon_days": horizon_days,
                "due_at": format_utc(due_at),
                "created_from_event_at": selection["event_created_at"],
            }
        )

    return result


def execute_due_tasks(
    store: DataStore,
    config: Config,
    api: GitHubAPI,
    health: RunHealth,
    now: datetime,
) -> None:
    owner_cache = store.owner_cache()
    tasks_processed = 0
    stop_for_rate_limit = False

    for bucket in store.due_task_buckets(now):
        if tasks_processed >= config.max_tasks_per_run or stop_for_rate_limit:
            break

        tasks = store.read_bucket_tasks(bucket)
        terminal_ids = store.terminal_task_ids(bucket)
        new_results: list[dict] = []
        owner_records: list[dict] = []
        attempts: list[dict] = []

        for task_id, task in sorted(tasks.items()):
            if task_id in terminal_ids:
                continue
            if tasks_processed >= config.max_tasks_per_run:
                break

            tasks_processed += 1
            health.counters["tasks_attempted"] += 1

            try:
                if task["task_type"] == "snapshot":
                    outcome = collect_snapshot(
                        task,
                        config,
                        api,
                        owner_cache,
                    )
                else:
                    outcome = collect_observation(task, api)

            except RateLimitDeferred:
                outcome = TaskOutcome(retry_reason="rate_limit_deferred")
                stop_for_rate_limit = True

            if outcome.terminal_record is not None:
                new_results.append(outcome.terminal_record)
                terminal_ids.add(task_id)
                health.counters["tasks_terminal"] += 1

            if outcome.owner_record is not None:
                owner_records.append(outcome.owner_record)
                owner_id = outcome.owner_record.get("owner_id")
                if isinstance(owner_id, int):
                    owner_cache[owner_id] = outcome.owner_record

            if outcome.retry_reason is not None:
                attempts.append(
                    {
                        "schema_version": 1,
                        "record_type": "attempt",
                        "protocol_version": config.protocol_version,
                        "task_id": task_id,
                        "sample_id": task["sample_id"],
                        "repository_id": task["repository_id"],
                        "task_type": task["task_type"],
                        "attempted_at": format_utc(utc_now()),
                        "retry_reason": outcome.retry_reason,
                    }
                )
                health.counters["tasks_retryable"] += 1

            if stop_for_rate_limit:
                break

        store.write_bucket_results(bucket, new_results)
        store.write_owner_records(owner_records, utc_now())
        store.write_attempt_records(attempts, utc_now())

        if set(tasks) <= terminal_ids:
            store.mark_bucket_complete(
                bucket,
                completed_at=utc_now(),
                task_count=len(tasks),
            )
            health.counters["task_buckets_completed"] += 1


def collect_snapshot(
    task: dict,
    config: Config,
    api: GitHubAPI,
    owner_cache: dict[int, dict],
) -> TaskOutcome:
    actual_at = utc_now()
    repository_id = task["repository_id"]
    due_at = parse_utc(task["due_at"])

    repository_response = api.get_json(f"/repositories/{repository_id}")

    if repository_response.status in {404, 410, 451}:
        return TaskOutcome(
            terminal_record=_inaccessible_snapshot(
                task,
                actual_at,
                repository_response.status,
            )
        )

    if repository_response.status != 200:
        return TaskOutcome(
            retry_reason=f"repository_http_{repository_response.status}"
        )

    repository = repository_response.json()
    if not isinstance(repository, dict):
        return TaskOutcome(retry_reason="invalid_repository_json")

    if repository.get("id") != repository_id:
        return TaskOutcome(retry_reason="repository_id_mismatch")

    full_name = str(repository.get("full_name") or "")
    owner = repository.get("owner") or {}
    owner_id = owner.get("id")
    owner_login = str(owner.get("login") or "")
    default_branch = str(repository.get("default_branch") or "")

    commit_sha: str | None = None
    commit_status = "missing"

    if full_name and default_branch:
        quoted_name = "/".join(
            urllib.parse.quote(part, safe="")
            for part in full_name.split("/", 1)
        )
        quoted_branch = urllib.parse.quote(default_branch, safe="")
        commit_response = api.get_json(
            f"/repos/{quoted_name}/commits/{quoted_branch}"
        )

        if commit_response.status == 200:
            commit = commit_response.json()
            if isinstance(commit, dict) and isinstance(commit.get("sha"), str):
                commit_sha = commit["sha"]
                commit_status = "available"
            else:
                return TaskOutcome(retry_reason="invalid_commit_json")
        elif commit_response.status in {404, 409, 422}:
            commit_status = f"unavailable_http_{commit_response.status}"
        else:
            return TaskOutcome(
                retry_reason=f"commit_http_{commit_response.status}"
            )

    readme_text = ""
    readme_path: str | None = None
    readme_hash: str | None = None
    readme_truncated = False
    readme_status = "not_requested"

    if commit_sha and full_name:
        quoted_name = "/".join(
            urllib.parse.quote(part, safe="")
            for part in full_name.split("/", 1)
        )
        quoted_sha = urllib.parse.quote(commit_sha, safe="")
        readme_response = api.get_raw(
            f"/repos/{quoted_name}/readme?ref={quoted_sha}",
            max_bytes=config.readme_max_bytes + 1,
        )

        if readme_response.status == 200:
            raw = readme_response.body
            readme_truncated = len(raw) > config.readme_max_bytes
            raw = raw[: config.readme_max_bytes]
            readme_hash = sha256_bytes(raw)
            readme_text = normalize_text(raw.decode("utf-8", errors="replace"))
            readme_status = "available"
            readme_path = readme_response.headers.get("content-location")
        elif readme_response.status == 404:
            readme_status = "missing"
        elif readme_response.status in {409, 422}:
            readme_status = f"unavailable_http_{readme_response.status}"
        else:
            return TaskOutcome(
                retry_reason=f"readme_http_{readme_response.status}"
            )

    owner_record: dict | None = None
    owner_metadata_status = "missing_owner_id"

    if isinstance(owner_id, int):
        cached = owner_cache.get(owner_id)
        if cached and _cache_is_fresh(cached, actual_at):
            owner_record = None
            owner_metadata_status = "cached"
        elif owner_login:
            quoted_owner = urllib.parse.quote(owner_login, safe="")
            owner_response = api.get_json(f"/users/{quoted_owner}")

            if owner_response.status == 200:
                owner_data = owner_response.json()
                if not isinstance(owner_data, dict):
                    return TaskOutcome(retry_reason="invalid_owner_json")

                owner_record = {
                    "schema_version": 1,
                    "record_type": "owner",
                    "protocol_version": config.protocol_version,
                    "sample_id": task["sample_id"],
                    "owner_id": owner_id,
                    "owner_group_key": owner_group_key(
                        owner_id,
                        config.sampling_key,
                    ),
                    "observed_at": format_utc(actual_at),
                    "account_type": owner_data.get("type"),
                    "account_created_at": owner_data.get("created_at"),
                    "followers": owner_data.get("followers"),
                    "following": owner_data.get("following"),
                    "public_repositories": owner_data.get("public_repos"),
                    "public_gists": owner_data.get("public_gists"),
                }
                owner_metadata_status = "available"
            elif owner_response.status in {404, 410, 451}:
                owner_metadata_status = (
                    f"unavailable_http_{owner_response.status}"
                )
            else:
                return TaskOutcome(
                    retry_reason=f"owner_http_{owner_response.status}"
                )

    description = normalize_text(repository.get("description"))
    topics = repository.get("topics")
    if not isinstance(topics, list):
        topics = []

    license_data = repository.get("license") or {}
    license_spdx = (
        license_data.get("spdx_id")
        if isinstance(license_data, dict)
        else None
    )

    eligible, reasons = evaluate_eligibility(
        repository=repository,
        description=description,
        readme_text=readme_text,
        commit_sha=commit_sha,
    )

    snapshot_record = {
        "schema_version": 1,
        "record_type": "snapshot",
        "protocol_version": config.protocol_version,
        "task_id": task["task_id"],
        "sample_id": task["sample_id"],
        "repository_id": repository_id,
        "owner_id": owner_id,
        "intended_snapshot_at": task["due_at"],
        "actual_snapshot_at": format_utc(actual_at),
        "snapshot_delay_seconds": int((actual_at - due_at).total_seconds()),
        "http_status": repository_response.status,
        "repository_status": "public",
        "current_full_name": full_name,
        "repository_created_at": repository.get("created_at"),
        "visibility": repository.get("visibility"),
        "private": repository.get("private"),
        "fork": repository.get("fork"),
        "archived": repository.get("archived"),
        "disabled": repository.get("disabled"),
        "mirror_url_present": bool(repository.get("mirror_url")),
        "default_branch": default_branch,
        "commit_sha": commit_sha,
        "commit_status": commit_status,
        "description": description,
        "topics": [normalize_text(str(topic)) for topic in topics],
        "license_spdx": license_spdx,
        "language": repository.get("language"),
        "repository_size_kib": repository.get("size"),
        "readme_path": readme_path,
        "readme_text": readme_text,
        "readme_sha256": readme_hash,
        "readme_truncated": readme_truncated,
        "readme_status": readme_status,
        "stars_at_snapshot": repository.get("stargazers_count"),
        "forks_at_snapshot": repository.get("forks_count"),
        "watchers_at_snapshot": repository.get("watchers_count"),
        "owner_metadata_status": owner_metadata_status,
        "eligible": eligible,
        "eligibility_protocol": "v1",
        "eligibility_reasons": reasons,
    }

    return TaskOutcome(
        terminal_record=snapshot_record,
        owner_record=owner_record,
    )


def collect_observation(
    task: dict,
    api: GitHubAPI,
) -> TaskOutcome:
    actual_at = utc_now()
    due_at = parse_utc(task["due_at"])
    repository_id = task["repository_id"]

    response = api.get_json(f"/repositories/{repository_id}")

    common = {
        "schema_version": 1,
        "record_type": "observation",
        "protocol_version": task.get("protocol_version", "v1"),
        "task_id": task["task_id"],
        "sample_id": task["sample_id"],
        "repository_id": repository_id,
        "horizon_days": task["horizon_days"],
        "intended_observation_at": task["due_at"],
        "actual_observation_at": format_utc(actual_at),
        "observation_delay_seconds": int((actual_at - due_at).total_seconds()),
        "http_status": response.status,
    }

    if response.status == 200:
        repository = response.json()
        if not isinstance(repository, dict):
            return TaskOutcome(retry_reason="invalid_observation_json")
        if repository.get("id") != repository_id:
            return TaskOutcome(retry_reason="observation_id_mismatch")

        return TaskOutcome(
            terminal_record={
                **common,
                "repository_status": "public",
                "stargazers_count": repository.get("stargazers_count"),
                "forks_count": repository.get("forks_count"),
                "open_issues_count": repository.get("open_issues_count"),
                "visibility": repository.get("visibility"),
                "archived": repository.get("archived"),
                "disabled": repository.get("disabled"),
                "current_full_name": repository.get("full_name"),
                "timeliness": classify_delay(actual_at - due_at),
            }
        )

    if response.status in {404, 410, 451}:
        return TaskOutcome(
            terminal_record={
                **common,
                "repository_status": "inaccessible",
                "stargazers_count": None,
                "forks_count": None,
                "open_issues_count": None,
                "visibility": None,
                "archived": None,
                "disabled": None,
                "current_full_name": None,
                "timeliness": classify_delay(actual_at - due_at),
            }
        )

    return TaskOutcome(
        retry_reason=f"observation_http_{response.status}"
    )


def evaluate_eligibility(
    repository: dict,
    description: str,
    readme_text: str,
    commit_sha: str | None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if repository.get("private") is True:
        reasons.append("not_public")
    if repository.get("visibility") not in {None, "public"}:
        reasons.append("not_public")
    if repository.get("fork") is True:
        reasons.append("fork")
    if repository.get("archived") is True:
        reasons.append("archived")
    if repository.get("disabled") is True:
        reasons.append("disabled")
    if repository.get("mirror_url"):
        reasons.append("mirror")
    if not commit_sha:
        reasons.append("no_launch_commit")

    has_usable_text = len(readme_text) >= 200 or len(description) >= 80
    if not has_usable_text:
        reasons.append("insufficient_project_text")

    return not reasons, reasons


def classify_delay(delay: timedelta) -> str:
    seconds = delay.total_seconds()
    if seconds <= 6 * 3600:
        return "on_time"
    if seconds <= 24 * 3600:
        return "moderately_late"
    return "late"


def _cache_is_fresh(record: dict, now: datetime) -> bool:
    observed_at = record.get("observed_at")
    if not observed_at:
        return False
    try:
        age = now - parse_utc(observed_at)
    except ValueError:
        return False
    return timedelta(0) <= age <= timedelta(hours=24)


def _inaccessible_snapshot(
    task: dict,
    actual_at: datetime,
    http_status: int,
) -> dict:
    due_at = parse_utc(task["due_at"])

    return {
        "schema_version": 1,
        "record_type": "snapshot",
        "protocol_version": task.get("protocol_version", "v1"),
        "task_id": task["task_id"],
        "sample_id": task["sample_id"],
        "repository_id": task["repository_id"],
        "owner_id": None,
        "intended_snapshot_at": task["due_at"],
        "actual_snapshot_at": format_utc(actual_at),
        "snapshot_delay_seconds": int((actual_at - due_at).total_seconds()),
        "http_status": http_status,
        "repository_status": "inaccessible",
        "commit_sha": None,
        "description": "",
        "topics": [],
        "readme_text": "",
        "readme_sha256": None,
        "readme_truncated": False,
        "stars_at_snapshot": None,
        "eligible": False,
        "eligibility_protocol": "v1",
        "eligibility_reasons": ["inaccessible_at_snapshot"],
    }
