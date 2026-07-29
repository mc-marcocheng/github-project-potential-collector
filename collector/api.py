from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Any


class RateLimitDeferred(RuntimeError):
    pass


@dataclass
class APIResponse:
    status: int
    body: bytes
    headers: dict[str, str]
    error: str | None = None

    def json(self) -> Any | None:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None


class GitHubAPI:
    def __init__(
        self,
        token: str,
        rate_limit_reserve: int,
        max_sleep_seconds: int,
    ):
        self.token = token
        self.rate_limit_reserve = rate_limit_reserve
        self.max_sleep_seconds = max_sleep_seconds
        self.remaining: int | None = None
        self.reset_epoch: int | None = None
        self.requests_made = 0

    def get_json(self, path: str) -> APIResponse:
        return self._request(
            path,
            accept="application/vnd.github+json",
            max_bytes=2_000_000,
        )

    def get_raw(self, path: str, max_bytes: int) -> APIResponse:
        return self._request(
            path,
            accept="application/vnd.github.raw+json",
            max_bytes=max_bytes,
        )

    def _request(
        self,
        path: str,
        accept: str,
        max_bytes: int,
    ) -> APIResponse:
        self._respect_known_rate_limit()

        if not path.startswith("/"):
            raise ValueError("GitHub API path must begin with '/'")

        url = f"https://api.github.com{path}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "project-potential-collector/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        last_error: str | None = None

        for attempt in range(3):
            try:
                self.requests_made += 1
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read(max_bytes + 1)
                    headers = self._headers(response.headers)
                    self._update_rate_limit(headers)
                    return APIResponse(
                        status=response.status,
                        body=body,
                        headers=headers,
                    )

            except urllib.error.HTTPError as exc:
                self.requests_made += 1
                body = exc.read(max_bytes + 1)
                headers = self._headers(exc.headers)
                self._update_rate_limit(headers)

                response = APIResponse(
                    status=exc.code,
                    body=body,
                    headers=headers,
                    error=f"http_{exc.code}",
                )

                if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2**attempt)
                    continue

                if exc.code == 403 and self.remaining == 0:
                    self._respect_known_rate_limit(force=True)

                return response

            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = type(exc).__name__
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue

        return APIResponse(
            status=0,
            body=b"",
            headers={},
            error=last_error or "network_error",
        )

    def _respect_known_rate_limit(self, force: bool = False) -> None:
        if self.remaining is None:
            return

        if self.remaining > self.rate_limit_reserve and not force:
            return

        now = int(time.time())
        reset = self.reset_epoch or now + 60
        wait_seconds = max(1, reset - now + 2)

        if wait_seconds <= self.max_sleep_seconds:
            time.sleep(wait_seconds)
            self.remaining = None
            self.reset_epoch = None
            return

        raise RateLimitDeferred(
            f"GitHub API limit is near exhaustion; reset in {wait_seconds}s"
        )

    def _update_rate_limit(self, headers: dict[str, str]) -> None:
        try:
            self.remaining = int(headers.get("x-ratelimit-remaining", ""))
        except ValueError:
            self.remaining = None

        try:
            self.reset_epoch = int(headers.get("x-ratelimit-reset", ""))
        except ValueError:
            self.reset_epoch = None

    @staticmethod
    def _headers(headers: Message) -> dict[str, str]:
        return {key.lower(): value for key, value in headers.items()}
