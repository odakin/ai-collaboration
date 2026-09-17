#!/usr/bin/env python3
"""Checks for claims about cosmological wavefunction coefficients and Gaussian two-mode states: complex-mode Gaussian moments, (A, C) <-> covariance map and purity with an explicit measure factor, box partial trace of a cubic wavefunction, on-shell psi2 with boundary terms, Ward identity on invariant boundary functionals, slow-roll coefficient extraction, and time-smeared commutators in a chosen momentum frame; --selftest.

Conventions (stated, not assumed): Psi = exp[-1/2 ∫_k psi2 ζζ - 1/6 ∫ psi3 ζζζ], ∫_k = (2π)^-3 ∫d^3k; finite box
∫_k -> V^-1 Σ_n, (2π)^3 δ(0) -> V; ζ_{-q} = ζ_q*; P_k = 1/(2 Re psi2).  Complex measure ∫d²X = mu ∫dRe X ∫dIm X with
mu kept explicit (mu = 2 is the Jacobian of dζ_q dζ_{-q}).  Rules: conventions/physics-verification-cycle.md
kernels 22-26 (#definition-level-judge).

Measured failure modes these functions exist to expose (each seen at least once when checking a paper):
- a constant factor in a Gaussian state (cross-term coefficient, prefactor, measure) that no single reading
  of the conventions absorbs — test trace, purity and covariance together with mu free;
- second-order slow-roll coefficients that are not those of the exact expression — test in power-law
  inflation (eps constant, eta = 0), where aH·tau and the Hankel index are exact;
- a closed-form coefficient of an integral dominated where the integrand's approximation fails;
- a statement about time-smeared observables that holds for one conjugate momentum and not for the
  momentum shifted by a boundary (total-derivative) term — the Wronskian is frame independent, the
  smeared commutator is not.
"""
import sys

import mpmath as mp
import numpy as np
import sympy as sp


# ---------------------------------------------------------------- Gaussian moments and two-mode states
def gauss_moment_1d(n, a):
    """∫ x^n exp(-a x^2) dx over R (a > 0)."""
    if n % 2:
        return sp.Integer(0)
    m = n // 2
    return sp.gamma(sp.Rational(2 * m + 1, 2)) / a ** sp.Rational(2 * m + 1, 2)


def complex_gauss_expect(poly, pairs):
    """Normalised expectation of a polynomial in (e, e*) symbols under prod exp(-a|e|^2); pairs = [(e, ec, a)]."""
    subs, reals = {}, []
    for (e, ec, a) in pairs:
        x, y = sp.symbols(f"x_{e.name} y_{e.name}", real=True)
        subs[e], subs[ec] = x + sp.I * y, x - sp.I * y
        reals += [(x, a), (y, a)]
    expr = sp.expand(poly.subs(subs, simultaneous=True))
    P = sp.Poly(expr, *[r[0] for r in reals])
    norm = sp.prod([gauss_moment_1d(0, a) for _, a in reals])
    total = sum(c * sp.prod([gauss_moment_1d(n, a) for (_, a), n in zip(reals, mono)]) for mono, c in P.terms())
    return sp.simplify(total / norm)


def pair_state_trace_purity(pref, ReA, ImA, cross, V, mu):
    """rho(s,t) = pref exp(-A|s|^2/V - A*|t|^2/V + cross (s t* + s* t)); returns (Tr rho, ∫∫|rho|^2) with measure mu."""
    a = 2 * ReA / V - 2 * cross
    tr = pref * mu * sp.pi / a
    Q = sp.Matrix([[2 * ReA / V, -2 * cross], [-2 * cross, 2 * ReA / V]])
    pur = pref**2 * mu**2 * (sp.pi / sp.sqrt(Q.det()))**2
    return sp.simplify(tr), sp.simplify(pur)


def covariance_from_AC(ReA, ImA, C):
    """M_ab = <{Φ^a, Φ^b}>' for the pair state with cross term C/V (pi = -iV d/dζ*)."""
    return sp.Matrix([[1, -ImA], [-ImA, ReA**2 + ImA**2 - C**2]]) / (2 * (ReA - C))


def AC_from_covariance(M):
    """Inverse of covariance_from_AC; C >= 0 (a density matrix, purity <= 1) iff det M >= 1/4."""
    d = M.det()
    return (4 * d + 1) / (4 * M[0, 0]), -M[0, 1] / M[0, 0], (4 * d - 1) / (4 * M[0, 0])


def box_partial_trace_cubic():
    """One system pair s and one environment pair (e1, e2), q + k + k' = 0, cubic term -(psi3/V^2)(s e1 e2 + c.c.).
    Returns dict with the O(psi3^2) cross coefficient of (s t* + s* t) and the diagonal |s|^2 coefficient in ln rho,
    together with C = P_k P_k' |psi3|^2 / V (the box form of C = 1/2 ∫∫ P P |psi3|^2 δ)."""
    V = sp.symbols("V", positive=True)
    R1, R2 = sp.symbols("R1 R2", positive=True)
    p3, p3c, lam = sp.symbols("psi3 psi3c lam")
    s, sc, t, tc, e1, e1c, e2, e2c = sp.symbols("s sc t tc e1 e1c e2 e2c")
    X = lam * (p3 / V**2) * (s * e1 * e2 + sc * e1c * e2c)
    Xt = lam * (p3c / V**2) * (tc * e1c * e2c + t * e1 * e2)
    ex = -(X + Xt)
    avg = sp.expand(complex_gauss_expect(sp.expand(1 + ex + ex**2 / 2), [(e1, e1c, 2 * R1 / V), (e2, e2c, 2 * R2 / V)]))
    ln2 = sp.expand(avg.coeff(lam, 2) - avg.coeff(lam, 1)**2 / 2)
    C = p3 * p3c / (4 * R1 * R2 * V)
    return {"cross": sp.simplify(ln2.coeff(s).coeff(tc)), "diag": sp.simplify(ln2.coeff(s).coeff(sc)), "C": C, "V": V,
            "psi3": p3, "R": (R1, R2)}


def box_bispectrum_from_wavefunction():
    """B defined by <ζ_-q ζ_-k ζ_-k'> = B V, at first order in Re psi3; expected -2 Re psi3 / prod(2 Re psi2)."""
    V = sp.symbols("V", positive=True)
    Rq, Rk, Rp, Re3, lam = sp.symbols("Rq Rk Rp Re3 lam", positive=True)
    s, sc, e1, e1c, e2, e2c = sp.symbols("s sc e1 e1c e2 e2c")
    w = 1 - lam * (2 * Re3 / V**2) * (s * e1 * e2 + sc * e1c * e2c)
    val = complex_gauss_expect(sp.expand(sc * e1c * e2c * w), [(s, sc, 2 * Rq / V), (e1, e1c, 2 * Rk / V), (e2, e2c, 2 * Rp / V)])
    return sp.simplify(val.coeff(lam, 1) / V), -2 * Re3 / (8 * Rq * Rk * Rp)


# ---------------------------------------------------------------- psi2 from the quadratic action
def psi2_onshell(nu, k, tau, z2, B):
    """psi2 = -i z^2 (K'(tau) - B) with K(t) = sqrt(t/tau) H^(2)_nu(-k t)/H^(2)_nu(-k tau) (Bunch–Davies, decays at -inf(1-i0)).
    z2 = z(tau)^2, B = coefficient of the boundary term -1/2 d/dtau(B |u|^2) in the Mukhanov–Sasaki action; B must include
    z'/z (= aH(1 + eta/2)) coming from u = -z ζ, plus any genuine boundary terms of the ζ action."""
    f = lambda t: mp.sqrt(t / tau) * mp.hankel2(nu, -k * t) / mp.hankel2(nu, -k * tau)
    return -1j * z2 * (mp.diff(f, tau) - B)


def powerlaw_background(eps):
    """Power-law inflation: eps constant, eta = 0; returns (nu, aH*tau) exactly."""
    eps = mp.mpf(eps)
    return mp.mpf(3) / 2 + eps / (1 - eps), -1 / (1 - eps)


def richardson_eps2(f, f0, f1, e0):
    """eps^2 coefficient of f(eps) = f0 + f1 eps + f2 eps^2 + O(eps^3) from f(e0), f(2 e0) (O(eps^3) removed linearly)."""
    g = lambda e: (f(e) - f0 - f1 * e) / e**2
    return 2 * g(e0) - g(2 * e0)


# ---------------------------------------------------------------- Ward identity on boundary functionals
_x, _y, _z = sp.symbols("x y z", real=True)
_X = (_x, _y, _z)


def ricci_scalar_conformally_flat(zeta, a):
    """R^(3) of h_ij = a^2 exp(2 zeta) delta_ij from Christoffel symbols."""
    h = sp.diag(*[a**2 * sp.exp(2 * zeta)] * 3)
    hi = h.inv()
    G = [[[sum(hi[i, l] * (sp.diff(h[l, j], _X[k]) + sp.diff(h[l, k], _X[j]) - sp.diff(h[j, k], _X[l])) for l in range(3)) / 2
           for k in range(3)] for j in range(3)] for i in range(3)]
    R = 0
    for j in range(3):
        for k in range(3):
            v = sum(sp.diff(G[i][j][k], _X[i]) - sp.diff(G[i][j][i], _X[k]) +
                    sum(G[i][i][p] * G[p][j][k] - G[i][k][p] * G[p][j][i] for p in range(3)) for i in range(3))
            R += hi[j, k] * v
    return sp.simplify(R)


def ward_check(density):
    """density(zeta) -> integrand of S = ∫d^3x density.  Returns (psi2(k), lim_{k1->0} psi3, (3 - k d_k) psi2 at k=p)
    with psi_n = -i x [coefficient of eps_1..eps_n] (box normalisation)."""
    k, p, d = sp.symbols("k p delta", positive=True)
    e1, e2, e3, s = sp.symbols("eps1 eps2 eps3 s")

    def extract(zeta, eps):
        ser = sp.expand(sp.series(density(s * zeta), s, 0, len(eps) + 1).removeO().subs(s, 1))
        c = ser
        for e in eps:
            c = sp.expand(c).coeff(e)
        c = c.subs({_x: 0, _y: 0, _z: 0})
        for e in (e1, e2, e3):
            c = c.subs(e, 0)
        return sp.simplify(c)

    ph = lambda kv: sp.exp(sp.I * (kv[0] * _x + kv[1] * _y + kv[2] * _z))
    psi2 = -sp.I * extract(e1 * sp.exp(sp.I * k * _z) + e2 * sp.exp(-sp.I * k * _z), (e1, e2))
    psi3 = -sp.I * extract(e1 * ph((d, 0, 0)) + e2 * ph((-d / 2, 0, p)) + e3 * ph((-d / 2, 0, -p)), (e1, e2, e3))
    return psi2, sp.simplify(sp.limit(psi3, d, 0)), sp.simplify((3 * psi2 - k * sp.diff(psi2, k)).subs(k, p))


# ---------------------------------------------------------------- time smearing and momentum frames
def smear(f, t, dt, n=60):
    """∫ W(t, t') f(t') dt' for a Gaussian window of width dt (Gauss–Hermite)."""
    x, w = np.polynomial.hermite.hermgauss(n)
    return sum(mp.mpf(wi) * f(t + mp.sqrt(2) * dt * mp.mpf(xi)) for xi, wi in zip(x, w)) / mp.sqrt(mp.pi)


def smeared_commutator(u, upi, t, dt):
    """c = <[ζ̄, π̄]>/i and 4 det M̄ for mode functions u (field) and upi (momentum) smeared with the same window.
    With the Wronskian upi u* - u upi* = -i, c = 1 and 4 det M = 1 at dt = 0."""
    ub, pb = smear(u, t, dt), smear(upi, t, dt)
    c = (ub * mp.conj(pb) - mp.conj(ub) * pb) / 1j
    det4 = 4 * (abs(ub)**2 * abs(pb)**2 - mp.re(ub * mp.conj(pb))**2)
    return c, det4


def shifted_momentum(u, upi, B):
    """Momentum shifted by a boundary term -B(t) ζ^2 in the Lagrangian: pi -> pi - 2 B ζ (Wronskian unchanged)."""
    return lambda t: upi(t) - 2 * B(t) * u(t)


# ---------------------------------------------------------------- selftest
def selftest() -> None:
    mp.mp.dps = 30
    ReA, ImA, C, V, mu = sp.symbols("ReA ImA C V mu", positive=True)
    tr, pur = pair_state_trace_purity(1, ReA, ImA, C / V, V, mu)
    assert sp.simplify(pur / tr**2 - (ReA - C) / (ReA + C)) == 0          # purity of the normalised state, any mu
    M = covariance_from_AC(ReA, ImA, C)
    assert sp.simplify(1 / (4 * M.det()) - (ReA - C) / (ReA + C)) == 0
    back = AC_from_covariance(M)
    assert all(sp.simplify(b - v) == 0 for b, v in zip(back, (ReA, ImA, C)))
    pt = box_partial_trace_cubic()
    assert sp.simplify(pt["cross"] - pt["C"] / pt["V"]) == 0                 # standard one-loop cross term
    B, Bexp = box_bispectrum_from_wavefunction()
    assert sp.simplify(B - Bexp) == 0
    # massless de Sitter, no genuine boundary term (B = z'/z = aH = -1/tau): psi2 = -i z^2 k^2 tau/(1 - i k tau) (textbook)
    k, tau, z2 = mp.mpf("0.7"), mp.mpf("-1.3"), mp.mpf("2.1")
    ps = psi2_onshell(mp.mpf(3) / 2, k, tau, z2, -1 / tau)
    assert abs(ps - (-1j * z2 * k**2 * tau / (1 - 1j * k * tau))) < mp.mpf("1e-20")
    nu, aHt = powerlaw_background("0.1")
    assert abs(nu - (mp.mpf(3) / 2 + mp.mpf("0.1") / mp.mpf("0.9"))) < 1e-25 and abs(aHt + 1 / mp.mpf("0.9")) < 1e-25
    f = lambda e: 2 - 3 * e + 5 * e**2 + 7 * e**3
    assert abs(richardson_eps2(f, 2, -3, mp.mpf("1e-4")) - 5) < 1e-6
    a = sp.symbols("a", positive=True)
    zf = sp.Function("Z")(*_X)
    Rs = ricci_scalar_conformally_flat(zf, a)
    for dens in (lambda zz: a**3 * sp.exp(3 * zz),
                 lambda zz: (a**3 * sp.exp(3 * zf) * Rs).subs(zf, zz).doit()):
        p2, l3, w = ward_check(dens)
        assert sp.simplify(l3 - w) == 0 and p2 != 0
    p2, l3, w = ward_check(lambda zz: a * (sum(sp.diff(zz, v)**2 for v in _X) * (1 + 2 * zz)))   # not invariant
    assert sp.simplify(l3 - w) != 0
    # smeared commutator: dt -> 0 limit and frame-independence of the pointwise Wronskian
    kk, eps_ = mp.mpf("0.01"), mp.mpf("0.01")
    N = mp.sqrt(1 / (4 * eps_ * kk**3))
    u = lambda t: N * (1 + 1j * kk * t) * mp.e**(-1j * kk * t)
    upi = lambda t: 2 * eps_ / t**2 * N * kk**2 * t * mp.e**(-1j * kk * t)
    Bt = lambda t: 9 * (-1 / t)**3
    for mom in (upi, shifted_momentum(u, upi, Bt)):
        t0 = mp.mpf(-1)
        wr = mom(t0) * mp.conj(u(t0)) - u(t0) * mp.conj(mom(t0))
        assert abs(wr + 1j) < 1e-15
        c, d4 = smeared_commutator(u, mom, t0, mp.mpf("1e-6"))
        assert abs(c - 1) < 1e-6 and abs(d4 - 1) < 1e-6
    print("cosmological_wavefunction selftest: PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        print(__doc__)
