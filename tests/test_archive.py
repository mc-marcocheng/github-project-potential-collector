import gzip
import json
import tempfile
import unittest
from pathlib import Path

from collector.archive import iter_repository_creations
from collector.util import parse_utc


class ArchiveTests(unittest.TestCase):
    def test_only_repository_create_events_are_selected(self):
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
                "payload": {"ref_type": "branch"},
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
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-03-01-12.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event) + "\n")

            results = list(
                iter_repository_creations(
                    path,
                    parse_utc("2026-03-01T12:00:00Z"),
                )
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].repository_id, 100)
        self.assertEqual(results[0].repository_name_at_discovery, "a/b")


if __name__ == "__main__":
    unittest.main()
