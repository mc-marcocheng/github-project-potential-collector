import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from collector.pipeline import build_tasks, classify_timeliness
from collector.protocol import observation_due_at, readiness_landmark


class PipelineTests(unittest.TestCase):
    def test_readiness_landmark_is_24_hours_after_launch(self):
        launch = datetime(2026, 7, 30, 21, 5, 52, tzinfo=UTC)

        self.assertEqual(
            readiness_landmark(launch),
            datetime(2026, 7, 31, 21, 5, 52, tzinfo=UTC),
        )

    def test_180_day_endpoint_is_181_days_after_launch(self):
        launch = datetime(2026, 7, 30, 21, 5, 52, tzinfo=UTC)

        self.assertEqual(
            observation_due_at(launch, 180),
            datetime(2027, 1, 27, 21, 5, 52, tzinfo=UTC),
        )

    def test_build_tasks_generates_four_tasks_per_repository(self):
        selection = {
            "sample_id": "sample-1",
            "repository_id": 123,
            "event_created_at": "2026-07-30T21:05:52Z",
            "launch_landmark_at": "2026-07-31T21:05:52Z",
            "protocol_version": "v1",
        }

        tasks = build_tasks(selection)

        self.assertEqual(len(tasks), 4)
        task_types = {t["task_type"] for t in tasks}
        self.assertEqual(task_types, {"snapshot", "stars-30d", "stars-90d", "stars-180d"})

    def test_horizon_tasks_are_based_on_t0_not_launch_time(self):
        selection = {
            "sample_id": "sample-1",
            "repository_id": 123,
            "event_created_at": "2026-07-30T21:05:52Z",
            "launch_landmark_at": "2026-07-31T21:05:52Z",
            "protocol_version": "v1",
        }

        tasks = build_tasks(selection)
        by_type = {t["task_type"]: t for t in tasks}

        snapshot_due = by_type["snapshot"]["due_at"]
        stars_30d_due = by_type["stars-30d"]["due_at"]

        self.assertEqual(snapshot_due, "2026-07-31T21:05:52Z")
        self.assertEqual(stars_30d_due, "2026-08-30T21:05:52Z")

    def test_classify_timeliness_on_time(self):
        self.assertEqual(classify_timeliness(0), "on_time")
        self.assertEqual(classify_timeliness(6 * 3600), "on_time")

    def test_classify_timeliness_moderately_late(self):
        self.assertEqual(classify_timeliness(6 * 3600 + 1), "moderately_late")
        self.assertEqual(classify_timeliness(24 * 3600), "moderately_late")

    def test_classify_timeliness_late(self):
        self.assertEqual(classify_timeliness(24 * 3600 + 1), "late")

    def test_classify_timeliness_negative_raises(self):
        with self.assertRaises(ValueError):
            classify_timeliness(-1)


if __name__ == "__main__":
    unittest.main()