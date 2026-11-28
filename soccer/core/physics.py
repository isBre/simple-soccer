"""The physics of a match: Haxball-style discs (ball, players, posts) and wall segments, at one step per tick. Positions and
velocities are complex numbers (vec.py). match.py moves the bodies and calls resolve() for the contacts every
tick; the constants are public (public.py), so anyone may simulate the bodies forward."""
import math

from .public import BALL_DAMPING

KIND_BALL, KIND_PLAYER, KIND_STATIC = 1, 2, 4


class Disc:
    """A circle with Haxball-style physical properties."""
    __slots__ = ("pos", "vel", "radius", "inv_mass", "damping", "b_coef", "kind")

    def __init__(self, pos=0j, radius=10.0, inv_mass=1.0, damping=BALL_DAMPING, b_coef=0.5, kind=KIND_BALL):
        self.pos = pos
        self.vel = 0j
        self.radius = radius
        self.inv_mass = inv_mass
        self.damping = damping
        self.b_coef = b_coef
        self.kind = kind


def collide_discs(a, b):
    """Pushes two overlapping discs apart (by their inverse masses) and bounces them (Haxball's rule)."""
    diff = a.pos - b.pos
    rsum = a.radius + b.radius
    d2 = diff.real * diff.real + diff.imag * diff.imag
    if d2 >= rsum * rsum or d2 < 0.00000001:
        return
    mass_sum = a.inv_mass + b.inv_mass
    if mass_sum == 0.0:
        return
    dist = math.sqrt(d2)
    nrm = diff / dist
    share = a.inv_mass / mass_sum
    pen = rsum - dist
    a.pos += nrm * pen * share
    b.pos -= nrm * pen * (1.0 - share)
    rv = a.vel - b.vel
    rel = rv.real * nrm.real + rv.imag * nrm.imag
    if rel < 0.0:
        bc = a.b_coef * b.b_coef
        j = rel * (bc + 1.0) / mass_sum
        a.vel -= nrm * j * a.inv_mass
        b.vel += nrm * j * b.inv_mass


def prepare_walls(segs):
    """Wall segments (a, b, bc) prepared for collide_walls: (a, b, bc, b - a, |b - a|^2, bounding box widened by 1 px)."""
    prep = []
    for a, b, c in segs:
        ab = b - a
        prep.append((a, b, c, ab, ab.real * ab.real + ab.imag * ab.imag, min(a.real, b.real) - 1.0, max(a.real, b.real) + 1.0,
                     min(a.imag, b.imag) - 1.0, max(a.imag, b.imag) + 1.0))
    return prep


def collide_walls(d, segs):
    """segs from prepare_walls. A disc outside a segment's box widened by its radius (+1 px) cannot touch it: skipped."""
    r = d.radius
    for a, b, c, ab, l2, x0, x1, y0, y1 in segs:
        pos = d.pos
        px, py = pos.real, pos.imag
        if px < x0 - r or px > x1 + r or py < y0 - r or py > y1 + r:
            continue
        pa = pos - a
        t = (pa.real * ab.real + pa.imag * ab.imag) / l2
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        diff = pos - (a + ab * t)
        d2 = diff.real * diff.real + diff.imag * diff.imag
        if d2 >= r * r or d2 < 0.00000001:
            continue
        dist = math.sqrt(d2)
        nrm = diff / dist
        d.pos += nrm * (r - dist)
        v = d.vel
        vn = v.real * nrm.real + v.imag * nrm.imag
        if vn < 0.0:
            d.vel -= nrm * vn * (1.0 + d.b_coef * c)


def resolve(movers, statics, bseg, pseg):
    """One tick of contacts: every pair of moving discs, every moving disc against the static ones (posts, obstacles), then
    each against its walls (bseg for the ball, pseg for the players; from prepare_walls)."""
    n = len(movers)
    collide = collide_discs
    walls = collide_walls
    for i in range(n):
        a = movers[i]
        ar = a.radius
        # the overlap test of collide_discs inline: most pairs are far apart and the call would return at once
        for j in range(i + 1, n):
            b = movers[j]
            diff = a.pos - b.pos
            rsum = ar + b.radius
            d2 = diff.real * diff.real + diff.imag * diff.imag
            if not (d2 >= rsum * rsum or d2 < 0.00000001):
                collide(a, b)
        for b in statics:
            diff = a.pos - b.pos
            rsum = ar + b.radius
            d2 = diff.real * diff.real + diff.imag * diff.imag
            if not (d2 >= rsum * rsum or d2 < 0.00000001):
                collide(a, b)
        walls(a, bseg if a.kind == KIND_BALL else pseg)
