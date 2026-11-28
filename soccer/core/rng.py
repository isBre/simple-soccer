"""Godot's RandomNumberGenerator (PCG32, core/math/random_pcg.h and random_number_generator.h of Godot 4.6), so a match
in Python draws exactly the kickoffs and penalties a Godot match draws with the same seed.

Bit for bit: seeding, state, randi, randi_range, randf, randf_range (matched Godot exactly; tests/test_rng.py guards the outputs).
randfn is computed like Godot's float version (32-bit cos and log); this module uses correctly rounded cos / log, while
the C library behind Godot is occasionally one bit off (macOS: about 1 draw in 250), so a rare randfn value differs in
its last bit (a relative 1e-7). Godot itself differs between platforms there (macOS libm vs Linux glibc)."""
import math
import struct

_MASK64 = (1 << 64) - 1
_MASK32 = (1 << 32) - 1
_MULT = 6364136223846793005
_DEFAULT_INC = 1442695040888963407      # PCG_DEFAULT_INC_64
_CMP_EPSILON = 0.00001
_TAU = 6.283185307179586


def _clz32(x: int) -> int:
    return 32 - x.bit_length()


_F32 = struct.Struct("<f")


def _f32(x: float) -> float:
    """Rounds a double to the nearest float32 (Godot computes these draws in 32-bit floats)."""
    return _F32.unpack(_F32.pack(x))[0]


_TAU32 = _f32(_TAU)


class RandomNumberGenerator:
    __slots__ = ("state", "inc", "_seed")

    def __init__(self, seed: int = 0):
        self.inc = _DEFAULT_INC
        self.seed = seed

    @property
    def seed(self) -> int:
        return self._seed

    @seed.setter
    def seed(self, s: int):
        s &= _MASK64
        self._seed = s
        # pcg32_srandom_r(&pcg, seed, inc)
        self.state = 0
        self.inc = ((_DEFAULT_INC << 1) | 1) & _MASK64
        self._next()
        self.state = (self.state + s) & _MASK64
        self._next()

    def _next(self) -> int:
        old = self.state
        self.state = (old * _MULT + self.inc) & _MASK64
        xorshifted = (((old >> 18) ^ old) >> 27) & _MASK32
        rot = old >> 59
        return ((xorshifted >> rot) | (xorshifted << ((-rot) & 31))) & _MASK32

    def randi(self) -> int:
        """Uniform 32-bit unsigned integer."""
        return self._next()

    def _bounded(self, bound: int) -> int:
        threshold = ((-bound) & _MASK32) % bound
        while True:
            r = self._next()
            if r >= threshold:
                return r % bound

    def randi_range(self, a: int, b: int) -> int:
        if a == b:
            return a
        return self._bounded((abs(a - b) + 1) & _MASK32) + min(a, b)

    def randf(self) -> float:
        """Uniform float in [0, 1] (a float32 value, as Godot's)."""
        proto = self._next()
        if proto == 0:
            return 0.0
        return _f32(math.ldexp(float(self._next() | 0x80000001), -32 - _clz32(proto)))

    def randd(self) -> float:
        proto = self._next()
        if proto == 0:
            return 0.0
        significand = ((self._next() << 32) | self._next() | 0x8000000000000001) & _MASK64
        return math.ldexp(float(significand), -64 - _clz32(proto))

    def randf_range(self, a: float, b: float) -> float:
        """Uniform in [a, b]; float32 arithmetic like Godot's RandomPCG::random(float, float)."""
        a, b = _f32(a), _f32(b)
        return _f32(_f32(self.randf() * _f32(b - a)) + a)

    def randfn(self, mean: float = 0.0, deviation: float = 1.0) -> float:
        """Normal distribution (Box-Muller) like Godot's float RandomPCG::randfn: two randf draws, 32-bit cos and log."""
        mean, deviation = _f32(mean), _f32(deviation)
        temp = self.randf()
        if temp < _CMP_EPSILON:
            temp = _f32(temp + _CMP_EPSILON)
        c = _f32(math.cos(_f32(_TAU32 * self.randf())))
        return _f32(mean + deviation * (c * math.sqrt(-2.0 * _f32(math.log(temp)))))

    def get_state(self) -> int:
        """The state as Godot reports it (RandomNumberGenerator.state, a signed 64-bit int)."""
        return self.state - (1 << 64) if self.state >= (1 << 63) else self.state

    def set_state(self, st: int):
        self.state = st & _MASK64
