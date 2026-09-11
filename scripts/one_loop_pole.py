#!/usr/bin/env python3
"""Exact 1/ε pole of one-loop Minkowski integrals with ≤ 2 propagators by large-loop-momentum expansion and covariant angular averaging (sympy, exact rationals only) — re-computes printed pole terms of self-energies, tadpoles and mixed two-point functions from printed Feynman rules; --selftest

Layer-1 hoist (2026-09-11) of the pole extractor that a blind referee wrote to re-compute a printed
one-loop two-point function (bubble + seagull + tadpole, and an undisplayed mixed amplitude) from the
printed Feynman rules, independently of the authors' tooling (the instance stays in a private paper repo).

Method.  Mostly-plus metric, denominators (p² + m² − i0) and ((p + q)² + m² − i0), D = 4 − 2ε:
    pole[ ∫ d^Dp/(2π)^D f(p) ] = (i / 16π²ε) · ⟨ f_{-4} ⟩ ,
f_{-4} = homogeneous degree −4 part of the large-p expansion
    1/(p² + m²) = Σ_j (−m²)^j / (p²)^{j+1},    1/((p+q)² + m²) = Σ_k (−X)^k / (p²)^{k+1},   X = 2 p·q + q² + m²,
and the covariant average of a degree-2k polynomial P_{2k} over (p²)^{k+2} is □_p^k P_{2k} / (2^k k! · 4·6···(2k+2))
times ∫ 1/(p²)² (four-dimensional tensor denominators; the differences are finite).  No Feynman parameters and
no tensor reduction are needed, so the pole of any polynomial numerator comes out exactly.
Calibration: ∫ 1/(p²+m²)² → 1,  ∫ 1/(p²+m²) → −m²,  QED vacuum polarisation of one Dirac fermion
tr[γ^μ(−p̸ − im)γ^ν(−(p̸+q̸) − im)] → (4/3)(q² η^{μν} − q^μ q^ν)   (all asserted by --selftest).

Traps this module guards against (conventions/scientific-computing.md#exact-rational-pipelines):
  * never pass results through sympy.nsimplify: with a large denominator it treats an exact Rational as a
    float and "identifies" an algebraic number (observed: 5·2^{307/522}·3^{5/29}… in place of a rational);
    inputs with Float atoms are rejected by require_exact();
  * routing: the second propagator carries p + q — for a p − q route substitute q → −q;
  * compare tensors only after lowering every index explicitly (printed formulas mix index positions).
The monomial selftests (rank 0–3 against the Feynman-parameter poles) catch the first two in seconds; run them
before trusting a new pipeline.

Usage
  from one_loop_pole import P, ETA, dot, raise_index, slash_with, PoleExtractor
  pe = PoleExtractor(m=sp.Rational(7, 5), q=[sp.Rational(3, 7), ...])     # q = lower components q_μ
  c  = pe.two_prop(numerator_polynomial_in_P)      # pole = c · i/(16π²ε)
  python3 one_loop_pole.py --selftest
"""
from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

import sympy as sp

ETA = sp.diag(-1, 1, 1, 1)
P = sp.symbols("p0:4", real=True)          # loop momentum, lower components p_μ


def raise_index(v):
    """v^μ = η^{μν} v_ν for a 4-list."""
    return [ETA[m, m] * v[m] for m in range(4)]


def dot(u, v):
    """u·v = u_μ η^{μν} v_ν for lower-component 4-lists."""
    return sum(u[m] * ETA[m, m] * v[m] for m in range(4))


def slash_with(gammas, v):
    """v_μ γ^μ for a list of upper-index gamma matrices (sympy) and lower components v_μ."""
    out = sp.zeros(*gammas[0].shape)
    for m in range(4):
        out += v[m] * gammas[m]
    return out


def require_exact(*exprs):
    """Reject inexact inputs: Float atoms mean an exact pipeline has been contaminated."""
    for e in exprs:
        e = sp.sympify(e)
        if e.atoms(sp.Float):
            raise TypeError(f"inexact input (Float atoms) in {e}: use sympy.Rational; never nsimplify exact results")


def _degree_parts(expr):
    """Split a polynomial in P into {total degree: homogeneous part}."""
    expr = sp.expand(expr)
    if expr == 0:
        return {}
    poly = sp.Poly(expr, *P)
    parts = {}
    for mono, coeff in poly.terms():
        d = sum(mono)
        parts[d] = parts.get(d, 0) + coeff * sp.prod([P[i] ** mono[i] for i in range(4)])
    return parts


def box(expr):
    """□_p = η^{μν} ∂_μ ∂_ν acting on a polynomial in the lower components p_μ."""
    return sum(ETA[mu, mu] * sp.diff(expr, P[mu], 2) for mu in range(4))


def average(poly_expr):
    """Covariant average: Σ_k □^k P_{2k} / (2^k k! · 4·6···(2k+2)) over the even-degree parts (coefficient of ∫ 1/(p²)²)."""
    total = sp.Integer(0)
    for d, part in _degree_parts(poly_expr).items():
        if d % 2:
            continue
        k = d // 2
        val = part
        for _ in range(k):
            val = box(val)
        total += val / (2 ** k * math.factorial(k) * math.prod([4 + 2 * j for j in range(k)]))
    return sp.expand(total)


class PoleExtractor:
    """pole[ ∫ d^Dp/(2π)^D N(p) / denominators ] = (i / 16π²ε) × coefficient, exactly."""

    def __init__(self, m, q):
        require_exact(m, *q)
        self.m = sp.sympify(m)
        self.q = [sp.sympify(x) for x in q]
        self.q2 = dot(self.q, self.q)
        self._X = 2 * dot(P, self.q) + self.q2 + self.m ** 2
        self._xparts = {0: {0: sp.Integer(1)}}

    def _minus_x_power(self, k):
        if k not in self._xparts:
            self._xparts[k] = _degree_parts((-self._X) ** k)
        return self._xparts[k]

    def one_prop(self, N):
        """Coefficient for ∫ N(p) / (p² + m²)."""
        require_exact(N)
        total = sp.Integer(0)
        for d, part in _degree_parts(N).items():
            if d % 2:
                continue
            total += average(part) * (-self.m ** 2) ** ((d + 2) // 2)
        return sp.expand(total)

    def two_prop(self, N):
        """Coefficient for ∫ N(p) / ((p² + m²)((p + q)² + m²)); the second propagator carries p + q."""
        require_exact(N)
        total = sp.Integer(0)
        for d, part in _degree_parts(N).items():
            for k in range(0, d + 1):
                xp = self._minus_x_power(k)
                for j in range(0, d // 2 + 1):
                    s = 2 * (j + k) - d            # degree taken from (−X)^k so that the total degree is −4
                    if s < 0 or s > k or s not in xp:
                        continue
                    total += average(part * (-self.m ** 2) ** j * xp[s])
        return sp.expand(total)


def feynman_parameter_reference(indices, q, m):
    """Pole of ∫ p_{α1}…p_{αn} / ((p²+m²)((p+q)²+m²)) from Feynman parameters, n ≤ 3 (units i/16π²ε, lower indices)."""
    q2 = dot(q, q)
    n = len(indices)
    if n == 0:
        return sp.Integer(1)
    if n == 1:
        (a,) = indices
        return -q[a] / 2
    if n == 2:
        a, b = indices
        return -ETA[a, b] * (m ** 2 + q2 / 6) / 2 + q[a] * q[b] / 3
    if n == 3:
        a, b, c = indices
        return (m ** 2 / 4 + q2 / 24) * (q[a] * ETA[b, c] + q[b] * ETA[a, c] + q[c] * ETA[a, b]) - q[a] * q[b] * q[c] / 4
    raise ValueError("reference implemented for rank ≤ 3")


def selftest() -> int:
    fails = []
    m = sp.Rational(7, 5)
    q = [sp.Rational(3, 7), sp.Rational(-2, 5), sp.Rational(5, 11), sp.Rational(1, 3)]
    pe = PoleExtractor(m, q)
    if pe.two_prop(sp.Integer(1)) != 1:
        fails.append("calibration ∫1/(p²+m²)² ≠ 1")
    if sp.expand(pe.one_prop(sp.Integer(1)) + m ** 2) != 0:
        fails.append("calibration ∫1/(p²+m²) ≠ −m²")
    for a, b in itertools.product(range(4), repeat=2):
        if sp.expand(pe.one_prop(P[a] * P[b]) - m ** 4 * ETA[a, b] / 4) != 0:
            fails.append(f"one-propagator rank 2 at {a}{b}")
    for n in (1, 2, 3):
        for idx in itertools.product(range(4), repeat=n):
            got = pe.two_prop(sp.prod([P[i] for i in idx]))
            if sp.expand(got - feynman_parameter_reference(idx, q, m)) != 0:
                fails.append(f"two-propagator rank {n} at {idx}")
    try:
        PoleExtractor(0.5, q)
        fails.append("require_exact accepted a Float mass")
    except TypeError:
        pass
    # QED vacuum polarisation: transverse, mass independent, |coefficient| = 4/3 (absolute-scale anchor)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dirac_algebra import exact
    gam = exact()
    Gs = gam["G"]
    I4 = sp.eye(4)
    Pq = [P[k] + q[k] for k in range(4)]
    A = -slash_with(Gs, P) - sp.I * m * I4
    B = -slash_with(Gs, Pq) - sp.I * m * I4
    qu = raise_index(q)
    q2 = dot(q, q)
    for mu, nu in itertools.product(range(4), repeat=2):
        got = pe.two_prop((Gs[mu] * A * Gs[nu] * B).trace())
        want = sp.Rational(4, 3) * (q2 * ETA[mu, nu] - qu[mu] * qu[nu])
        if sp.expand(got - want) != 0:
            fails.append(f"QED vacuum polarisation at {mu}{nu}: {got} vs {want}")
    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("one_loop_pole selftest: calibrations, one-propagator rank 2, two-propagator ranks 1-3 vs Feynman parameters "
          "(84 components), Float rejection, QED vacuum polarisation (4/3)(q^2 eta - q q) — all PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
