import unittest

from calc import clamp


class ClampTests(unittest.TestCase):
    def test_below_lower_returns_lower(self):
        self.assertEqual(clamp(-5, 0, 10), 0)

    def test_inside_bounds_returns_value(self):
        self.assertEqual(clamp(4, 0, 10), 4)

    def test_above_upper_returns_upper(self):
        self.assertEqual(clamp(42, 0, 10), 10)

    def test_at_lower_bound_returns_lower(self):
        self.assertEqual(clamp(0, 0, 10), 0)

    def test_at_upper_bound_returns_upper(self):
        self.assertEqual(clamp(10, 0, 10), 10)

    def test_negative_bounds(self):
        self.assertEqual(clamp(-7, -10, -3), -7)
        self.assertEqual(clamp(-99, -10, -3), -10)
        self.assertEqual(clamp(5, -10, -3), -3)

    def test_invalid_bounds_raise_value_error(self):
        with self.assertRaises(ValueError):
            clamp(5, 10, 0)

    def test_invalid_bounds_raise_even_when_value_inside_swapped(self):
        with self.assertRaises(ValueError):
            clamp(5, 5, 5 - 1)


if __name__ == "__main__":
    unittest.main()
