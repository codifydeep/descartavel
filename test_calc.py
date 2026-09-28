import unittest

from calc import absolute, add, cube, double, multiply, negate, square


class CalcTests(unittest.TestCase):
    def test_add_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_add_negative(self):
        self.assertEqual(add(-2, 3), 1)


class MultiplyTests(unittest.TestCase):
    def test_multiply_positive(self):
        self.assertEqual(multiply(2, 3), 6)

    def test_multiply_by_zero(self):
        self.assertEqual(multiply(5, 0), 0)

    def test_multiply_negative(self):
        self.assertEqual(multiply(-2, 4), -8)

    def test_multiply_commutative(self):
        self.assertEqual(multiply(7, 3), multiply(3, 7))


class SquareTests(unittest.TestCase):
    def test_square_positive(self):
        self.assertEqual(square(4), 16)

    def test_square_negative(self):
        self.assertEqual(square(-3), 9)


class CubeTests(unittest.TestCase):
    def test_cube_positive(self):
        self.assertEqual(cube(3), 27)

    def test_cube_negative(self):
        self.assertEqual(cube(-2), -8)


class NegateTests(unittest.TestCase):
    def test_negate_positive(self):
        self.assertEqual(negate(3), -3)

    def test_negate_negative(self):
        self.assertEqual(negate(-2), 2)


class AbsoluteTests(unittest.TestCase):
    def test_absolute_positive(self):
        self.assertEqual(absolute(3), 3)

    def test_absolute_negative(self):
        self.assertEqual(absolute(-2), 2)


class DoubleTests(unittest.TestCase):
    def test_double_positive(self):
        self.assertEqual(double(3), 6)

    def test_double_negative(self):
        self.assertEqual(double(-2), -4)
