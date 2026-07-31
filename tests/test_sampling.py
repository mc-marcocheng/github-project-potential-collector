import unittest

from collector.sampling import (is_selected, owner_group_key, sample_id,
                                sample_value)


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.key = b"x" * 32

    def test_deterministic(self):
        self.assertEqual(
            sample_value(123, self.key),
            sample_value(123, self.key),
        )

    def test_value_range(self):
        value = sample_value(456, self.key)
        self.assertGreaterEqual(value, 0)
        self.assertLess(value, 1)

    def test_probability_extremes(self):
        self.assertFalse(is_selected(1, self.key, 0))
        self.assertTrue(is_selected(1, self.key, 1))

    def test_domain_separation(self):
        self.assertNotEqual(
            sample_id(123, self.key),
            owner_group_key(123, self.key),
        )

    def test_higher_probability_selects_superset_for_same_key(self):
        key = b"x" * 32
        repository_ids = range(1, 10_000)

        low = {
            repository_id
            for repository_id in repository_ids
            if is_selected(repository_id, key, 0.002)
        }
        high = {
            repository_id
            for repository_id in repository_ids
            if is_selected(repository_id, key, 0.02)
        }

        self.assertTrue(low <= high)


if __name__ == "__main__":
    unittest.main()
