"""2-D vectors as Python complex numbers: x = z.real, y = z.imag. Addition, scaling and abs() run in C, which keeps the
per-tick physics and AI fast without numpy (numpy is slower than plain Python on objects this small). The engine (match.py,
rating.py) and the AI (ai/) share these helpers; their names mirror Godot's Vector2 methods, from the port."""
import cmath
import math

INF = math.inf


def dot(a: complex, b: complex) -> float:
    return a.real * b.real + a.imag * b.imag


def cross(a: complex, b: complex) -> float:
    """Godot's Vector2.cross: a.x * b.y - a.y * b.x."""
    return a.real * b.imag - a.imag * b.real


def normalized(z: complex) -> complex:
    l = abs(z)
    return z / l if l > 0.0 else 0j


def limit_length(z: complex, n: float = 1.0) -> complex:
    l = abs(z)
    return z / l * n if l > n else z


def from_angle(a: float) -> complex:
    return cmath.rect(1.0, a)


def angle(z: complex) -> float:
    return cmath.phase(z)


def rotated(z: complex, a: float) -> complex:
    return z * cmath.rect(1.0, a)


def lerp(a, b, t: float):
    """a + (b - a) * t, for floats and vectors alike."""
    return a + (b - a) * t


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def roundi(x: float) -> int:
    """Godot's roundi: halves away from zero (Python's round() rounds halves to even)."""
    return int(math.floor(x + 0.5)) if x >= 0.0 else -int(math.floor(-x + 0.5))
