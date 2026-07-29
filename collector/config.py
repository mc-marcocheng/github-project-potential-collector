from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from collector.util import parse_utc


class ConfigurationError(ValueError):
    pass


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def integer_environment(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def float_environment(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc


@dataclass(frozen=True)
class Config:
    protocol_version: str
    start_hour: datetime
    sampling_probability: float
    sampling_key: bytes

    github_api_token: str
    data_repo_url: str
    data_repo_token: str
    data_repo_branch: str

    safety_lag_hours: int
    max_archive_hours_per_run: int
    max_tasks_per_run: int

    api_rate_limit_reserve: int
    api_max_sleep_seconds: int
    readme_max_bytes: int

    git_retries: int

    @classmethod
    def from_environment(cls) -> "Config":
        probability = float_environment("SAMPLING_PROBABILITY", -1.0)
        if not 0.0 < probability <= 1.0:
            raise ConfigurationError(
                "SAMPLING_PROBABILITY must be greater than 0 and at most 1"
            )

        sampling_key_text = required_environment("SAMPLING_KEY")
        if len(sampling_key_text.encode("utf-8")) < 32:
            raise ConfigurationError(
                "SAMPLING_KEY must contain at least 32 UTF-8 bytes"
            )

        start_hour = parse_utc(required_environment("START_HOUR"))
        if start_hour.minute or start_hour.second or start_hour.microsecond:
            raise ConfigurationError("START_HOUR must be aligned to a UTC hour")

        protocol_version = os.environ.get("PROTOCOL_VERSION", "v1").strip()
        if protocol_version != "v1":
            raise ConfigurationError(
                "This production collector only accepts PROTOCOL_VERSION=v1"
            )

        config = cls(
            protocol_version=protocol_version,
            start_hour=start_hour,
            sampling_probability=probability,
            sampling_key=sampling_key_text.encode("utf-8"),
            github_api_token=required_environment("GH_API_TOKEN"),
            data_repo_url=required_environment("DATA_REPO_URL"),
            data_repo_token=required_environment("DATA_REPO_TOKEN"),
            data_repo_branch=os.environ.get("DATA_REPO_BRANCH", "main"),
            safety_lag_hours=integer_environment("SAFETY_LAG_HOURS", 3),
            max_archive_hours_per_run=integer_environment(
                "MAX_ARCHIVE_HOURS_PER_RUN", 8
            ),
            max_tasks_per_run=integer_environment("MAX_TASKS_PER_RUN", 250),
            api_rate_limit_reserve=integer_environment(
                "API_RATE_LIMIT_RESERVE", 75
            ),
            api_max_sleep_seconds=integer_environment(
                "API_MAX_SLEEP_SECONDS", 120
            ),
            readme_max_bytes=integer_environment("README_MAX_BYTES", 65_536),
            git_retries=integer_environment("GIT_RETRIES", 3),
        )

        if config.safety_lag_hours < 2:
            raise ConfigurationError("SAFETY_LAG_HOURS must be at least 2")
        if config.max_archive_hours_per_run < 1:
            raise ConfigurationError("MAX_ARCHIVE_HOURS_PER_RUN must be positive")
        if config.max_tasks_per_run < 1:
            raise ConfigurationError("MAX_TASKS_PER_RUN must be positive")
        if config.readme_max_bytes < 1_024:
            raise ConfigurationError("README_MAX_BYTES is unreasonably small")

        return config
