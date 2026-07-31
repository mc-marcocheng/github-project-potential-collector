import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from collector.storage import DataStore
from collector.util import floor_hour, parse_utc


class StorageTests(unittest.TestCase):
    def test_task_round_trip_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DataStore(root, run_id="run1")
            store.initialize()

            task = {
                "schema_version": 1,
                "record_type": "task",
                "protocol_version": "v1",
                "task_id": "task-1",
                "sample_id": "sample-1",
                "repository_id": 123,
                "task_type": "snapshot",
                "horizon_days": None,
                "due_at": "2026-03-01T12:00:00Z",
                "created_from_event_at": "2026-02-28T12:00:00Z",
            }

            store.write_tasks([task])
            buckets = store.due_task_buckets(
                parse_utc("2026-03-01T13:00:00Z")
            )

            self.assertEqual(len(buckets), 1)
            tasks = store.read_bucket_tasks(buckets[0])
            self.assertEqual(tasks["task-1"]["repository_id"], 123)

            store.write_bucket_results(
                buckets[0],
                [{"task_id": "task-1", "record_type": "snapshot"}],
            )
            terminal = store.terminal_task_ids(buckets[0])
            self.assertEqual(terminal, {"task-1"})

            store.mark_bucket_complete(
                buckets[0],
                parse_utc("2026-03-01T13:01:00Z"),
                1,
            )
            self.assertEqual(
                store.due_task_buckets(
                    parse_utc("2026-03-01T14:00:00Z")
                ),
                [],
            )

    def test_current_hour_bucket_is_not_due(self):
        now = datetime(2026, 7, 31, 0, 17, tzinfo=UTC)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DataStore(root, run_id="run1")
            store.initialize()

            task = {
                "schema_version": 1,
                "record_type": "task",
                "protocol_version": "v1",
                "task_id": "task-1",
                "sample_id": "sample-1",
                "repository_id": 123,
                "task_type": "snapshot",
                "horizon_days": None,
                "due_at": "2026-07-31T00:57:00Z",
                "created_from_event_at": "2026-07-30T21:05:52Z",
            }

            store.write_tasks([task])
            buckets = store.due_task_buckets(now)

            self.assertEqual(buckets, [])

    def test_completed_hour_bucket_is_due(self):
        now = datetime(2026, 7, 31, 1, 0, tzinfo=UTC)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DataStore(root, run_id="run1")
            store.initialize()

            task = {
                "schema_version": 1,
                "record_type": "task",
                "protocol_version": "v1",
                "task_id": "task-1",
                "sample_id": "sample-1",
                "repository_id": 123,
                "task_type": "snapshot",
                "horizon_days": None,
                "due_at": "2026-07-31T00:57:00Z",
                "created_from_event_at": "2026-07-30T21:05:52Z",
            }

            store.write_tasks([task])
            buckets = store.due_task_buckets(now)

            self.assertEqual(len(buckets), 1)

    def test_bucket_with_pending_task_is_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DataStore(root, run_id="run1")
            store.initialize()

            task = {
                "schema_version": 1,
                "record_type": "task",
                "protocol_version": "v1",
                "task_id": "task-1",
                "sample_id": "sample-1",
                "repository_id": 123,
                "task_type": "snapshot",
                "horizon_days": None,
                "due_at": "2026-03-01T12:00:00Z",
                "created_from_event_at": "2026-02-28T12:00:00Z",
            }

            store.write_tasks([task])
            bucket = store.due_task_buckets(
                parse_utc("2026-03-01T13:00:00Z")
            )[0]

            # Write only a partial result (not for task-1)
            store.write_bucket_results(
                bucket,
                [{"task_id": "other-task", "record_type": "snapshot"}],
            )

            # Bucket should still be due because task-1 has no
            # terminal result.
            self.assertEqual(
                len(store.due_task_buckets(parse_utc("2026-03-01T14:00:00Z"))),
                1,
            )


if __name__ == "__main__":
    unittest.main()
