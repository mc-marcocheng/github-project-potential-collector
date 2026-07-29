import gzip
import json
import tempfile
import unittest
from pathlib import Path

from collector.archive import iter_repository_launches
from collector.util import parse_utc


class ArchiveTests(unittest.TestCase):
    def test_repository_launch_events_are_selected(self):
        events = [
            {
                "id": "1",
                "type": "CreateEvent",
                "created_at": "2026-03-01T12:01:00Z",
                "repo": {"id": 100, "name": "a/b"},
                "payload": {"ref_type": "repository"},
            },
            {
                "id": "2",
                "type": "CreateEvent",
                "created_at": "2026-03-01T12:02:00Z",
                "repo": {"id": 101, "name": "a/c"},
                "payload": {
                    "ref_type": "branch",
                    "ref": "feature-branch",
                    "master_branch": "main",
                },
            },
            {
                "id": "3",
                "type": "PushEvent",
                "created_at": "2026-03-01T12:03:00Z",
                "repo": {"id": 102, "name": "a/d"},
                "payload": {},
            },
            {
                "id": "4",
                "type": "CreateEvent",
                "created_at": "2026-03-01T12:04:00Z",
                "repo": {"id": 100, "name": "a/b"},
                "payload": {"ref_type": "repository"},
            },
            {
                "id": "5",
                "type": "CreateEvent",
                "created_at": "2026-03-01T12:05:00Z",
                "repo": {"id": 103, "name": "a/e"},
                "payload": {
                    "ref_type": "branch",
                    "ref": "main",
                    "master_branch": "main",
                },
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-03-01-12.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event) + "\n")

            results = list(
                iter_repository_launches(
                    path,
                    parse_utc("2026-03-01T12:00:00Z"),
                )
            )

        self.assertEqual(
            [result.repository_id for result in results],
            [100, 103],
        )
        self.assertEqual(
            results[0].discovery_event_kind,
            "repository_create",
        )
        self.assertEqual(
            results[1].discovery_event_kind,
            "initial_default_branch_create",
        )


if __name__ == "__main__":
    unittest.main()
