import unittest
from datetime import UTC, datetime

from collector.protocol import observation_due_at, readiness_landmark


class ProtocolTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()