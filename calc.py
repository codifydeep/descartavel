"""Disposable evaluation fixture, not product code."""


def add(left: int, right: int) -> int:
    return left + right


def multiply(left: int, right: int) -> int:
    return left * right


def square(value: int) -> int:
    return value * value


def cube(value: int) -> int:
    return value * value * value


def double(value: int) -> int:
    return value * 2


def negate(value: int) -> int:
    return -value


def absolute(value: int) -> int:
    if value < 0:
        return -value
    return value


def clamp(value: int, lower: int, upper: int) -> int:
    if lower > upper:
        raise ValueError("lower bound must not exceed upper bound")
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
