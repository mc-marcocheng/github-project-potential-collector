import unittest
from datetime import UTC, datetime

from collector.util import format_utc, normalize_text, parse_utc


class UtilityTests(unittest.TestCase):
    def test_utc_round_trip(self):
        value = datetime(2026, 3, 1, 12, 30, tzinfo=UTC)
        self.assertEqual(parse_utc(format_utc(value)), value)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            parse_utc("2026-03-01T12:00:00")

    def test_text_normalization(self):
        self.assertEqual(
            normalize_text("hello  \r\nworld\x00\r\n"),
            "hello\nworld",
        )


if __name__ == "__main__":
    unittest.main()
