#!/usr/bin/env python3
"""Exact rational Taylor jets of tensor fields at a point and the curved geometry built on them (metric, Christoffel, Riemann, spin connection, curvature of a connection, torsion, Weyl rescaling, duals), every convention an argument; --selftest.

Why: an identity of differential geometry (an off-shell decomposition of a density, the conformal transformation of an
invariant, the response of a term to a local rescaling) can be decided exactly at one random point.  Each field is a
polynomial in x with random rational coefficients; values and derivatives at x = 0 follow from the Leibniz rule on
(value, first, second) jets, and the only inverse is the matrix inverse at the point, propagated by
d(M^-1) = -M^-1 dM M^-1.  No finite differences, no floating point, no symbolic inverse metric.  A coefficient can be
FITTED from an overdetermined set of configurations (solve_exact) and then verified on fresh ones, so a wrong ansatz
fails instead of being absorbed.  This module holds the engine and the conventions as arguments; the identity under
test, its coefficients and its printed form stay with the project that claims them.

Conventions (explicit; each is asserted by --selftest):
  jets        Jet(val, d, dd): d[p, ...] = d_p(field)(0), dd[p, q, ...] = d_p d_q(field)(0), derivative indices in front.
              order = 0, 1 or 2 derivative levels kept; a product or sum has the lower order of its operands.
  vierbein    E.val[a, m] = e^a_m;  geometry()["Ei"].val[a, m] = e_a^m (inverse);  frame indices move with eta.
  metric      g_mn = eta_ab e^a_m e^b_n;  Gamma^l_{rm} = (1/2) g^{lc} (-d_c g_{rm} + d_r g_{mc} + d_m g_{cr}).
  connection  Omega^a_{bm} = e^a_l (d_m e_b^l + Gamma^l_{rm} e_b^r), the torsion-free connection of
              D_m V^a = d_m V^a + omega^a_{bm} V^b (vierbein postulate).
  Riemann     R^m_{nrs} = s (d_r G^m_{ns} - d_s G^m_{nr} + G^m_{lr} G^l_{ns} - G^m_{ls} G^l_{nr}), s = riemann_sign;
              Ric_ns = R^m_{nms}; with s = +1 the scalar curvature is positive on spheres.
  curvature   F^a_{bmn}(omega) = d_m om^a_{bn} - d_n om^a_{bm} + c [om_m, om_n]^a_b, c = comm_sign (a foil handle).
  torsion     T^a_{mn} = w (d_m e^a_n - d_n e^a_m + om^a_{bm} e^b_n - om^a_{bn} e^b_m), w = weight of the antisymmetrization.
  Weyl        e -> W e with W = e^sigma as a jet of value lam: conformal weights show up as powers of lam at the point.
  Levi-Civita eps_{01...} = +1 (lower symbol); raising every index gives det(eta^-1) times the symbol, so
              eps_{a...} eps^{a...} = sign(det eta) D!: a dictionary between a tensor and its dual changes sign with
              the signature, and a Euclidean dictionary must not be carried over to a Lorentzian check.

Usage
  import random
  from exact_jets import Fraction, minkowski, random_vierbein, random_frame_one_form, geometry, field_strength, jadd
  rng = random.Random(1); eta = minkowski(4)
  E = random_vierbein(rng); K = random_frame_one_form(rng, eta)      # order-2 and order-1 jets
  geo = geometry(E, eta)                                             # dict: Ei g ginv Gamma Omega Riem Ric Rscalar
  F = field_strength(jadd(geo["Omega"], K.truncate(1)))              # curvature of Omega + K at the point
  python3 exact_jets.py --selftest

Sibling: clifford_jets.py keeps polynomial identities in x and in symbolic external fields (operators acting on basis
jets); it is a separate representation on purpose (see its docstring).  The general reasoning for checking on jets is in
conventions/physics-verification-cycle.md#operator-identity-on-jets.
"""
from __future__ import annotations

import itertools
import math
import random
import sys
from fractions import Fraction

import numpy as np

einsum = np.einsum


def zeros(shape):
    return np.full(shape, Fraction(0), dtype=object)


def diagonal(entries):
    out = zeros((len(entries), len(entries)))
    for i, v in enumerate(entries):
        out[i, i] = Fraction(v)
    return out


def minkowski(dim=4):
    """diag(-1, 1, ..., 1) as an exact matrix."""
    return diagonal([-1] + [1] * (dim - 1))


def euclidean(dim=4):
    return diagonal([1] * dim)


def frac_random(rng, scale=Fraction(1, 7)):
    return Fraction(rng.randint(-6, 6), rng.randint(1, 9)) * scale


# ----------------------------------------------------------------------------------------------------
# exact jets
# ----------------------------------------------------------------------------------------------------
class Jet:
    """Truncated Taylor data of a tensor field at x = 0.  order = number of derivative levels kept."""

    def __init__(self, val, d=None, dd=None):
        self.val = val
        self.d = d            # shape (D,) + val.shape
        self.dd = dd          # shape (D, D) + val.shape
        self.order = 0 if d is None else (1 if dd is None else 2)

    @staticmethod
    def const(val, dim=None):
        """A constant tensor as an order-2 jet; dim defaults to the length of the first axis of val."""
        if dim is None:
            if not val.shape:
                raise ValueError("a scalar constant needs dim")
            dim = val.shape[0]
        s = val.shape
        return Jet(val, zeros((dim,) + s), zeros((dim, dim) + s))

    def deriv(self):
        """The field d_mu(.) as a jet of one lower order; new leading index = mu."""
        if self.order < 1:
            raise ValueError("no derivative data")
        return Jet(self.d, None if self.order < 2 else self.dd)

    def truncate(self, order):
        if order >= self.order:
            return self
        return Jet(self.val, self.d if order >= 1 else None, None)


def jmul(spec, X: Jet, Y: Jet) -> Jet:
    """Leibniz product/contraction.  spec is an einsum spec for the VALUES, e.g. 'am,bn->mn' style;
    derivative indices are prepended automatically."""
    order = min(X.order, Y.order)
    lhs, out = spec.split("->")
    sx, sy = lhs.split(",")
    val = einsum(f"{sx},{sy}->{out}", X.val, Y.val)
    if order == 0:
        return Jet(val)
    d = einsum(f"p{sx},{sy}->p{out}", X.d, Y.val) + einsum(f"{sx},p{sy}->p{out}", X.val, Y.d)
    if order == 1:
        return Jet(val, d)
    dd = (einsum(f"pq{sx},{sy}->pq{out}", X.dd, Y.val)
          + einsum(f"p{sx},q{sy}->pq{out}", X.d, Y.d)
          + einsum(f"q{sx},p{sy}->pq{out}", X.d, Y.d)
          + einsum(f"{sx},pq{sy}->pq{out}", X.val, Y.dd))
    return Jet(val, d, dd)


def jadd(X: Jet, Y: Jet, cy=Fraction(1)) -> Jet:
    order = min(X.order, Y.order)
    val = X.val + cy * Y.val
    if order == 0:
        return Jet(val)
    d = X.d + cy * Y.d
    if order == 1:
        return Jet(val, d)
    return Jet(val, d, X.dd + cy * Y.dd)


def jscale(X: Jet, c) -> Jet:
    return Jet(c * X.val, None if X.d is None else c * X.d, None if X.dd is None else c * X.dd)


def jtranspose(X: Jet, perm) -> Jet:
    """Permute the value indices; derivative indices stay in front."""
    val = np.transpose(X.val, perm)
    d = None if X.d is None else np.transpose(X.d, (0,) + tuple(p + 1 for p in perm))
    dd = None if X.dd is None else np.transpose(X.dd, (0, 1) + tuple(p + 2 for p in perm))
    return Jet(val, d, dd)


def mat_inv_exact(M):
    """Exact inverse of a square Fraction matrix (Gauss-Jordan)."""
    n = M.shape[0]
    A = [[Fraction(M[i, j]) for j in range(n)] + [Fraction(int(i == j)) for j in range(n)] for i in range(n)]
    for col in range(n):
        piv = next(r for r in range(col, n) if A[r][col] != 0)
        A[col], A[piv] = A[piv], A[col]
        p = A[col][col]
        A[col] = [v / p for v in A[col]]
        for r in range(n):
            if r != col and A[r][col] != 0:
                f = A[r][col]
                A[r] = [a - f * b for a, b in zip(A[r], A[col])]
    out = zeros((n, n))
    for i in range(n):
        for j in range(n):
            out[i, j] = A[i][n + j]
    return out


def det_exact(M):
    """Exact determinant of a square Fraction matrix (Gaussian elimination)."""
    n = M.shape[0]
    A = [[Fraction(M[i, j]) for j in range(n)] for i in range(n)]
    det = Fraction(1)
    for col in range(n):
        piv = next((r for r in range(col, n) if A[r][col] != 0), None)
        if piv is None:
            return Fraction(0)
        if piv != col:
            A[col], A[piv] = A[piv], A[col]
            det = -det
        det *= A[col][col]
        for r in range(col + 1, n):
            f = A[r][col] / A[col][col]
            A[r] = [a - f * b for a, b in zip(A[r], A[col])]
    return det


def jet_inverse(E: Jet) -> Jet:
    """Jet of the matrix inverse.  E.val[a, m] = e^a_m; returns Ei with Ei.val[m, a] = e_a^m
    (matrix inverse: sum_m e^a_m e_b^m = delta^a_b)."""
    dim = E.val.shape[0]
    M0 = mat_inv_exact(E.val)                       # M0[m, a]
    if E.order == 0:
        return Jet(M0)
    # d(M^-1) = - M^-1 dM M^-1
    d = zeros((dim, dim, dim))
    for p in range(dim):
        d[p] = -M0 @ E.d[p] @ M0
    if E.order == 1:
        return Jet(M0, d)
    dd = zeros((dim, dim, dim, dim))
    for p in range(dim):
        for q in range(dim):
            dd[p, q] = -(d[q] @ E.d[p] @ M0) - (M0 @ E.dd[p, q] @ M0) - (M0 @ E.d[p] @ d[q])
    return Jet(M0, d, dd)


def det_jet(E: Jet) -> Jet:
    """det e with its first derivative (order-1 scalar jet): d det e = det e tr(e^-1 d e)."""
    dim = E.val.shape[0]
    det0 = det_exact(E.val)
    Minv = mat_inv_exact(E.val)                     # [m, a]
    d = zeros((dim,))
    for p in range(dim):
        d[p] = det0 * einsum("am,ma->", E.d[p], Minv)
    return Jet(np.array(det0, dtype=object).reshape(()), d)


def solve_exact(rows, rhs):
    """Exact solve of an overdetermined system (Fractions).  Returns (solution, every row satisfied);
    raises ValueError when the columns are rank deficient."""
    n = len(rows[0])
    # pick n independent rows by Gauss elimination on the augmented matrix, then verify all rows
    A = [list(r) + [b] for r, b in zip(rows, rhs)]
    m = len(A)
    piv_cols = []
    r = 0
    for c in range(n):
        piv = next((i for i in range(r, m) if A[i][c] != 0), None)
        if piv is None:
            continue
        A[r], A[piv] = A[piv], A[r]
        p = A[r][c]
        A[r] = [v / p for v in A[r]]
        for i in range(m):
            if i != r and A[i][c] != 0:
                f = A[i][c]
                A[i] = [a - f * b for a, b in zip(A[i], A[r])]
        piv_cols.append(c)
        r += 1
    if len(piv_cols) < n:
        raise ValueError("rank deficient")
    sol = [Fraction(0)] * n
    for i, c in enumerate(piv_cols):
        sol[c] = A[i][n]
    consistent = all(sum(a * s for a, s in zip(row, sol)) == b for row, b in zip(rows, rhs))
    return sol, consistent


# ----------------------------------------------------------------------------------------------------
# random polynomial fields
# ----------------------------------------------------------------------------------------------------
def random_vierbein(rng, dim=4) -> Jet:
    """Order-2 jet e^a_m = delta + random, invertible for the default scale in practice (the inverse raises if not)."""
    val = zeros((dim, dim))
    for a in range(dim):
        val[a, a] = Fraction(1)
    for a in range(dim):
        for m in range(dim):
            val[a, m] += frac_random(rng, Fraction(1, 5))
    d = zeros((dim, dim, dim))
    for p in range(dim):
        for a in range(dim):
            for m in range(dim):
                d[p, a, m] = frac_random(rng)
    dd = zeros((dim, dim, dim, dim))
    for p in range(dim):
        for q in range(p, dim):
            for a in range(dim):
                for m in range(dim):
                    v = frac_random(rng)
                    dd[p, q, a, m] = v
                    dd[q, p, a, m] = v
    return Jet(val, d, dd)


def random_frame_one_form(rng, eta, antisym=True) -> Jet:
    """Order-1 jet of K^a_{b m}; with antisym, K_{ab m} := eta_{ac} K^c_{b m} is antisymmetric in ab
    (a contorsion, or any metric-compatible shift of a connection)."""
    dim = eta.shape[0]
    eta_inv = mat_inv_exact(eta)

    def block(gen):
        Klow = zeros((dim, dim, dim))
        for a in range(dim):
            for b in range(dim):
                for m in range(dim):
                    if antisym:
                        if a < b:
                            v = gen()
                            Klow[a, b, m] = v
                            Klow[b, a, m] = -v
                    else:
                        Klow[a, b, m] = gen()
        return einsum("ac,cbm->abm", eta_inv, Klow)   # raise the first index
    val = block(lambda: frac_random(rng))
    d = zeros((dim, dim, dim, dim))
    for p in range(dim):
        d[p] = block(lambda: frac_random(rng))
    return Jet(val, d)


def random_weyl_factor(rng, lam, dim=4):
    """W = e^sigma as an order-2 scalar jet of value lam, with random d sigma and dd sigma at the point.
    Returns (W, d sigma, dd sigma).  Take lam a rational whose needed powers stay rational."""
    ds = np.array([frac_random(rng) for _ in range(dim)], dtype=object)
    dds = zeros((dim, dim))
    for p in range(dim):
        for q in range(p, dim):
            v = frac_random(rng)
            dds[p, q] = v
            dds[q, p] = v
    val = np.array(Fraction(lam), dtype=object).reshape(())
    return Jet(val, lam * ds, lam * (dds + einsum("p,q->pq", ds, ds))), ds, dds


def rescale(E: Jet, W: Jet) -> Jet:
    """The rescaled vierbein W e^a_m."""
    return jmul(",am->am", W, E)


# ----------------------------------------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------------------------------------
def geometry(E: Jet, eta, riemann_sign=1):
    """Dict of jets and tensors at the point: Ei (e_a^m as [a, m]), g, ginv, Gamma (order 1), Omega (order 1),
    Riem (R^m_{nrs}), Ric, Rscalar.  Needs an order-2 vierbein jet."""
    eta_inv = mat_inv_exact(eta)
    Ei_ma = jet_inverse(E)                                   # [m, a]
    Ei = jtranspose(Ei_ma, (1, 0))                           # [a, m] = e_a^m
    ETAJ = Jet.const(eta)
    ETAIJ = Jet.const(eta_inv)
    tmp = jmul("ab,am->bm", ETAJ, E)                         # eta_ab e^a_m -> [b, m]
    g = jmul("bm,bn->mn", tmp, E)
    tmp2 = jmul("ab,am->bm", ETAIJ, Ei)
    ginv = jmul("bm,bn->mn", tmp2, Ei)
    dg = g.deriv()                                           # [c, r, m] = d_c g_{r m}   (order 1)
    t1 = jtranspose(dg, (0, 1, 2))                           # d_c g_{rm}       indices (c, r, m)
    t2 = jtranspose(dg, (1, 2, 0))                           # d_r g_{m c}: value[r, m, c] -> [c, r, m]
    t3 = jtranspose(dg, (2, 0, 1))                           # d_m g_{c r}: value[m, c, r] -> [c, r, m]
    comb = jadd(jadd(jscale(t1, Fraction(-1)), t2), t3)      # [c, r, m]
    Gamma = jscale(jmul("lc,crm->lrm", ginv, comb), Fraction(1, 2))   # order 1
    dEi = Ei.deriv()                                         # [m, b, l] = d_m e_b^l (order 1)
    term1 = jtranspose(dEi, (1, 2, 0))                       # [b, l, m]
    term2 = jmul("lrm,br->blm", Gamma, Ei)                   # Gamma^l_{rm} e_b^r -> [b, l, m]
    inner = jadd(term1, term2)                               # [b, l, m]
    Omega = jmul("al,blm->abm", E, inner)                    # [a, b, m]  (order 1)
    dG = Gamma.deriv().val                                   # [p, m, n, s] = d_p Gamma^m_{n s}
    G = Gamma.val
    Riem = riemann_sign * (einsum("rmns->mnrs", dG) - einsum("smnr->mnrs", dG)
                           + einsum("mlr,lns->mnrs", G, G) - einsum("mls,lnr->mnrs", G, G))
    Ric = einsum("mnms->ns", Riem)
    Rscalar = einsum("ns,ns->", ginv.val, Ric)
    return dict(Ei=Ei, g=g, ginv=ginv, Gamma=Gamma, Omega=Omega, Riem=Riem, Ric=Ric, Rscalar=Rscalar)


def field_strength(omega: Jet, comm_sign=Fraction(1)):
    """F^a_{b m n} at the point, for an order-1 connection jet; matrices (om_m)^a_b = om^a_{b m}."""
    dom = omega.deriv().val                                  # [p, a, b, n] = d_p om^a_{b n}
    om = omega.val
    return (einsum("mabn->abmn", dom) - einsum("nabm->abmn", dom)
            + comm_sign * (einsum("acm,cbn->abmn", om, om) - einsum("acn,cbm->abmn", om, om)))


def torsion(E: Jet, omega: Jet, weight=Fraction(1, 2)):
    """T^a_{m n} at the point; weight = the weight of the antisymmetrization (1/2 or 1)."""
    dE = E.deriv().val                                       # [m, a, n]
    om = omega.val
    return weight * (einsum("man->amn", dE) - einsum("nam->amn", dE)
                     + einsum("abm,bn->amn", om, E.val) - einsum("abn,bm->amn", om, E.val))


def box_and_grad(geo, ds, dds):
    """(box sigma, (d sigma)^2) at the point from d sigma and dd sigma."""
    gi = geo["ginv"].val
    G = geo["Gamma"].val
    box = einsum("mn,mn->", gi, dds - einsum("lmn,l->mn", G, ds))
    grad2 = einsum("mn,m,n->", gi, ds, ds)
    return box, grad2


def curvature_squares(geo):
    """(Riem^2, Ric^2, R) at the point, indices moved with g one at a time."""
    g = geo["g"].val
    gi = geo["ginv"].val
    Rlow = einsum("ma,anrs->mnrs", g, geo["Riem"])      # R_{m n r s}
    Rup = einsum("mnrs,ma->anrs", Rlow, gi)
    Rup = einsum("anrs,nb->abrs", Rup, gi)
    Rup = einsum("abrs,rc->abcs", Rup, gi)
    Rup = einsum("abcs,sd->abcd", Rup, gi)
    Ric = geo["Ric"]
    return (einsum("mnrs,mnrs->", Rlow, Rup), einsum("ns,na,sb,ab->", Ric, gi, gi, Ric), einsum("ns,ns->", gi, Ric))


def weyl_squared(geo):
    """(C^2, R) with C^2 = Riem^2 - (4/(D-2)) Ric^2 + (2/((D-1)(D-2))) R^2, D >= 3."""
    dim = geo["g"].val.shape[0]
    riem2, ric2, R = curvature_squares(geo)
    return riem2 - Fraction(4, dim - 2) * ric2 + Fraction(2, (dim - 1) * (dim - 2)) * R * R, R


def cov_deriv_lower(geo, T: Jet):
    """nabla_r T_{i j ...} at the point for an all-lower tensor jet of order >= 1 (Levi-Civita); result [r, i, j, ...]."""
    G = geo["Gamma"].val
    idx = "ijklmnop"[:T.val.ndim]
    out = T.deriv().val
    for slot, name in enumerate(idx):
        swapped = idx[:slot] + "a" + idx[slot + 1:]
        out = out - einsum(f"a{name}r,{swapped}->r{idx}", G, T.val)
    return out


# ----------------------------------------------------------------------------------------------------
# antisymmetrization and duals
# ----------------------------------------------------------------------------------------------------
def perm_parity(p) -> int:
    return (-1) ** sum(1 for i, j in itertools.combinations(range(len(p)), 2) if p[i] > p[j])


def antisymmetrize(T):
    """Total antisymmetrization on all indices, weight 1/n! (a projector)."""
    n = T.ndim
    out = zeros(T.shape)
    for p in itertools.permutations(range(n)):
        out = out + perm_parity(p) * np.transpose(T, p)
    return out * Fraction(1, math.factorial(n))


def levi_civita(eta):
    """(eps_low, eps_up): eps_{01...} = +1 and eps^{a...} = det(eta^-1) eps_{a...}."""
    dim = eta.shape[0]
    low = zeros((dim,) * dim)
    for p in itertools.permutations(range(dim)):
        low[p] = Fraction(perm_parity(p))
    return low, det_exact(mat_inv_exact(eta)) * low


def dual_vector(T: Jet, det_e: Jet, eps_up) -> Jet:
    """S^m = (1/(D-1)!) eps^{m i j ...} T_{i j ...} / det e for a rank D-1 lower-index jet (order 1).
    T_{i j ...} T^{i j ...} = sign(det eta) (D-1)! S_m S^m for totally antisymmetric T."""
    dim = eps_up.shape[0]
    inv0 = 1 / det_e.val[()]
    inv_d = np.array([-det_e.d[p] * inv0 * inv0 for p in range(dim)], dtype=object)
    inv = Jet(np.array(inv0, dtype=object).reshape(()), inv_d)
    idx = "ijklmnop"[:dim - 1]
    tmp = jmul(f"s{idx},{idx}->s", Jet.const(eps_up).truncate(1), T)
    return jscale(jmul(",m->m", inv, tmp), Fraction(1, math.factorial(dim - 1)))


# ----------------------------------------------------------------------------------------------------
# selftest (textbook anchors only; each check is independent of the others' state)
# ----------------------------------------------------------------------------------------------------
def _conformally_flat(x0, eta):
    """e^a_m = Omega delta^a_m with Omega = 2/(1 + eta(x, x)) expanded around the rational point x0: stereographic
    coordinates of the constant-curvature space of radius 1, jets written out by hand from the closed form."""
    dim = eta.shape[0]
    xl = einsum("ab,b->a", eta, x0)
    u = 1 + einsum("a,a->", xl, x0)
    om = 2 / u
    dom = np.array([-2 * om * xl[p] / u for p in range(dim)], dtype=object)
    ddom = zeros((dim, dim))
    for p in range(dim):
        for q in range(dim):
            ddom[p, q] = -2 * om * eta[p, q] / u + 8 * om * xl[p] * xl[q] / (u * u)
    identity = euclidean(dim)
    return Jet(om * identity, einsum("p,am->pam", dom, identity), einsum("pq,am->pqam", ddom, identity))


def _all_zero(a):
    return all(v == 0 for v in np.asarray(a, dtype=object).flat)


def selftest() -> int:
    import sympy as sp

    failed: list = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failed.append(label)

    # jmul against an independent path: polynomial product differentiated by sympy
    rng = random.Random(1)
    xs = sp.symbols("x0:3")

    def poly_and_jet():
        c0 = frac_random(rng)
        c1 = [frac_random(rng) for _ in range(3)]
        c2 = [[frac_random(rng) for _ in range(3)] for _ in range(3)]
        c2 = [[(c2[i][j] + c2[j][i]) / 2 for j in range(3)] for i in range(3)]
        R = lambda v: sp.Rational(v.numerator, v.denominator)
        f = R(c0) + sum(R(c1[i]) * xs[i] for i in range(3)) + sum(R(c2[i][j]) * xs[i] * xs[j] / 2 for i in range(3) for j in range(3))
        J = Jet(np.array(c0, dtype=object).reshape(()), np.array(c1, dtype=object), np.array(c2, dtype=object))
        return f, J
    (f1, J1), (f2, J2) = poly_and_jet(), poly_and_jet()
    prod = sp.expand(f1 * f2)
    J = jmul(",->", J1, J2)
    at0 = {x: 0 for x in xs}
    to_frac = lambda e: Fraction(int(sp.Rational(e).p), int(sp.Rational(e).q))
    ok = J.val == to_frac(prod.subs(at0))                     # einsum returns a plain Fraction for a scalar value
    ok = ok and all(J.d[i] == to_frac(sp.diff(prod, xs[i]).subs(at0)) for i in range(3))
    ok = ok and all(J.dd[i, j] == to_frac(sp.diff(prod, xs[i], xs[j]).subs(at0)) for i in range(3) for j in range(3))
    check("jmul: the Leibniz rule through second order agrees with the product of polynomials differentiated by sympy", ok)

    rng = random.Random(2)
    E = random_vierbein(rng)
    Ei = jet_inverse(E)
    unit = jmul("am,mb->ab", E, Ei)
    check("jet_inverse: e e^-1 = 1 through second order",
          all(unit.val[i, j] == int(i == j) for i in range(4) for j in range(4)) and _all_zero(unit.d) and _all_zero(unit.dd))

    # det_jet against the 2 x 2 formula built with jmul; det_exact against sympy
    rng = random.Random(3)
    E2 = random_vierbein(rng, dim=2)
    comp = lambda a, m: Jet(np.array(E2.val[a, m], dtype=object).reshape(()),
                            np.array([E2.d[p, a, m] for p in range(2)], dtype=object))
    det2 = jadd(jmul(",->", comp(0, 0), comp(1, 1)), jmul(",->", comp(0, 1), comp(1, 0)), Fraction(-1))
    dj = det_jet(E2)
    check("det_jet: value and first derivative agree with the 2 x 2 formula", dj.val[()] == det2.val and _all_zero(dj.d - det2.d))
    M = random_vierbein(random.Random(4), dim=5).val
    sm = sp.Matrix(5, 5, lambda i, j: sp.Rational(M[i, j].numerator, M[i, j].denominator))
    check("det_exact agrees with sympy on a 5 x 5 rational matrix", det_exact(M) == to_frac(sm.det()))
    swap = zeros((3, 3))
    swap[0, 1] = swap[1, 0] = swap[2, 2] = Fraction(1)
    check("det_exact: a pivot swap flips the sign", det_exact(swap) == -1)

    # constant curvature: the full tensor, both signatures, several dimensions, off the origin
    for dim, sig in ((2, "E"), (3, "E"), (4, "E"), (4, "L"), (3, "L")):
        eta = euclidean(dim) if sig == "E" else minkowski(dim)
        x0 = np.array([Fraction(i + 1, 5) for i in range(dim)], dtype=object)
        E = _conformally_flat(x0, eta)
        geo = geometry(E, eta)
        g, gv = geo["g"].val, geo["Riem"]
        want = einsum("mr,ns->mnrs", euclidean(dim), g) - einsum("ms,nr->mnrs", euclidean(dim), g)
        check(f"geometry: R^m_(nrs) = delta^m_r g_ns - delta^m_s g_nr on the unit constant-curvature space (D = {dim}, {sig})",
              _all_zero(gv - want))
        check(f"geometry: scalar curvature = D(D-1) > 0 (D = {dim}, {sig})", geo["Rscalar"] == dim * (dim - 1))
        flipped = geometry(E, eta, riemann_sign=-1)
        check(f"geometry: riemann_sign = -1 flips the scalar curvature (D = {dim}, {sig})", flipped["Rscalar"] == -dim * (dim - 1))

    # a generic vierbein: the connection and the symmetries of the curvature, with no closed form to lean on
    rng = random.Random(5)
    eta = minkowski(4)
    E = random_vierbein(rng)
    geo = geometry(E, eta)
    Om = geo["Omega"]
    OmLow = einsum("ac,cbm->abm", eta, Om.val)
    check("Omega: torsion-free and antisymmetric in the frame pair", _all_zero(torsion(E, Om)) and _all_zero(OmLow + np.transpose(OmLow, (1, 0, 2))))
    dE = E.deriv().val
    postulate = dE + einsum("abm,bn->man", Om.val, E.val) - einsum("lnm,al->man", geo["Gamma"].val, E.val)
    check("Omega: the vierbein postulate d_m e^a_n + omega^a_{bm} e^b_n - Gamma^l_{nm} e^a_l = 0", _all_zero(postulate))
    Rl = einsum("ma,anrs->mnrs", geo["g"].val, geo["Riem"])
    ok = _all_zero(Rl + np.transpose(Rl, (1, 0, 2, 3))) and _all_zero(Rl + np.transpose(Rl, (0, 1, 3, 2)))
    ok = ok and _all_zero(Rl - np.transpose(Rl, (2, 3, 0, 1)))
    ok = ok and _all_zero(Rl + np.transpose(Rl, (0, 2, 3, 1)) + np.transpose(Rl, (0, 3, 1, 2)))
    check("Riemann: pair antisymmetry, pair symmetry and the first Bianchi identity on a random vierbein", ok)
    F = field_strength(Om)
    conv = einsum("ar,sb,rsmn->abmn", E.val, geo["Ei"].val.T, geo["Riem"])
    check("field_strength: F^a_{bmn}(Omega) = e^a_r e_b^s R^r_{smn}", _all_zero(F - conv))
    check("field_strength: the commutator sign is seen (foil comm_sign = -1)", not _all_zero(field_strength(Om, Fraction(-1)) - conv))
    K = random_frame_one_form(rng, eta)
    Klow = einsum("ac,cbm->abm", eta, K.val)
    check("random_frame_one_form: antisymmetric in the frame pair after lowering", _all_zero(Klow + np.transpose(Klow, (1, 0, 2))))
    Kn = random_frame_one_form(rng, eta, antisym=False)
    KnLow = einsum("ac,cbm->abm", eta, Kn.val)
    check("random_frame_one_form: antisym = False is generic (foil)", not _all_zero(KnLow + np.transpose(KnLow, (1, 0, 2))))
    T = torsion(E, jadd(Om, K.truncate(1)), weight=Fraction(1, 2))
    want = Fraction(1, 2) * (einsum("abm,bn->amn", K.val, E.val) - einsum("abn,bm->amn", K.val, E.val))
    check("torsion: T^a_{mn}(Omega + K) = w (K^a_{bm} e^b_n - K^a_{bn} e^b_m) at w = 1/2", _all_zero(T - want))
    check("torsion: weight = 1 doubles it", _all_zero(torsion(E, jadd(Om, K.truncate(1)), weight=Fraction(1)) - 2 * want))

    # metric compatibility and the product rule on every slot
    gj = geo["g"].truncate(1)
    check("cov_deriv_lower: nabla g = 0", _all_zero(cov_deriv_lower(geo, gj)))
    rng = random.Random(6)
    vec = lambda: Jet(np.array([frac_random(rng) for _ in range(4)], dtype=object),
                      np.array([[frac_random(rng) for _ in range(4)] for _ in range(4)], dtype=object))
    U, V, W = vec(), vec(), vec()
    UVW = jmul("ij,k->ijk", jmul("i,j->ij", U, V), W)
    nU, nV, nW = cov_deriv_lower(geo, U), cov_deriv_lower(geo, V), cov_deriv_lower(geo, W)
    rhs = einsum("ri,j,k->rijk", nU, V.val, W.val) + einsum("i,rj,k->rijk", U.val, nV, W.val) + einsum("i,j,rk->rijk", U.val, V.val, nW)
    check("cov_deriv_lower: Leibniz on a rank-3 product, slot by slot", _all_zero(cov_deriv_lower(geo, UVW) - rhs))

    # conformal transformation of R, det e and C^2 (textbook, for general D)
    for dim, eta, lam in ((3, euclidean(3), 4), (4, minkowski(4), 4), (5, minkowski(5), 4)):
        rng = random.Random(100 + dim)
        E = random_vierbein(rng, dim=dim)
        W, ds, dds = random_weyl_factor(rng, lam, dim=dim)
        geo = geometry(E, eta)
        geo2 = geometry(rescale(E, W), eta)
        box, grad2 = box_and_grad(geo, ds, dds)
        C2, R = weyl_squared(geo)
        C2p, Rp = weyl_squared(geo2)
        check(f"conformal: R' = lam^-2 (R - 2(D-1) box s - (D-1)(D-2) (d s)^2) (D = {dim})",
              Rp * lam ** 2 == R - 2 * (dim - 1) * box - (dim - 1) * (dim - 2) * grad2)
        det0, det2 = det_exact(E.val), det_exact(rescale(E, W).val)
        check(f"conformal: det e' = lam^D det e (D = {dim})", det2 == lam ** dim * det0)
        check(f"conformal: C'^2 = lam^-4 C^2 for the general-D Weyl square (D = {dim})", C2p * lam ** 4 == C2)
        if dim == 3:
            check("conformal: C^2 = 0 identically in D = 3", C2 == 0 and C2p == 0)
        if dim == 5:
            naive = lambda G: (lambda riem2, ric2, r: riem2 - 2 * ric2 + r * r / 3)(*curvature_squares(G))
            check("conformal: the D = 4 coefficients are not covariant in D = 5 (foil)", naive(geo2) * lam ** 4 != naive(geo))

    # antisymmetrization and the sign of the dual dictionary
    rng = random.Random(7)
    T3 = np.array([[[frac_random(rng) for _ in range(4)] for _ in range(4)] for _ in range(4)], dtype=object)
    A3 = antisymmetrize(T3)
    check("antisymmetrize: a projector onto totally antisymmetric tensors",
          _all_zero(A3 + np.transpose(A3, (1, 0, 2))) and _all_zero(A3 + np.transpose(A3, (0, 2, 1))) and _all_zero(antisymmetrize(A3) - A3))
    for dim in (3, 4):
        for sig, eta in (("E", euclidean(dim)), ("L", minkowski(dim))):
            low, up = levi_civita(eta)
            s = det_exact(eta) / abs(det_exact(eta))
            check(f"levi_civita: eps_(01...) = +1 and eps eps = sign(det eta) D! (D = {dim}, {sig})",
                  low[tuple(range(dim))] == 1 and einsum(low, list(range(dim)), up, list(range(dim))) == s * math.factorial(dim))
    for sig, eta in (("E", euclidean(4)), ("L", minkowski(4))):
        rng = random.Random(8)
        E = random_vierbein(rng)
        geo = geometry(E, eta)
        _, up = levi_civita(eta)
        raw = lambda: np.array([[[frac_random(rng) for _ in range(4)] for _ in range(4)] for _ in range(4)], dtype=object)
        val = antisymmetrize(raw())
        dT = np.array([antisymmetrize(raw()) for _ in range(4)], dtype=object)
        Tj = Jet(val, dT)
        S = dual_vector(Tj, det_jet(E), up)
        gi, g = geo["ginv"].val, geo["g"].val
        T2 = einsum("ijk,ia,jb,kc,abc->", val, gi, gi, gi, val)
        Slow = einsum("mn,n->m", g, S.val)
        s = det_exact(eta) / abs(det_exact(eta))
        check(f"dual_vector: T_(ijk) T^(ijk) = sign(det eta) 3! S_m S^m with the curved measure ({sig})",
              T2 == s * 6 * einsum("m,m->", Slow, S.val))
        dj = det_jet(E)
        dS = Fraction(1, 6) * einsum("mijk,pijk->pm", up, dT) / dj.val[()] - einsum("p,m->pm", dj.d, S.val) / dj.val[()]
        check(f"dual_vector: d_p S^m = (1/3!) eps d_p T / det e - (d_p det e / det e) S^m ({sig})", _all_zero(S.d - dS))

    # the exact solver
    sol, consistent = solve_exact([[Fraction(1), Fraction(2)], [Fraction(3), Fraction(4)], [Fraction(5), Fraction(6)]],
                                  [Fraction(5), Fraction(11), Fraction(17)])
    check("solve_exact: overdetermined and consistent", sol == [1, 2] and consistent)
    _, consistent = solve_exact([[Fraction(1), Fraction(2)], [Fraction(3), Fraction(4)], [Fraction(5), Fraction(6)]],
                                [Fraction(5), Fraction(11), Fraction(18)])
    check("solve_exact: an inconsistent row is reported, not absorbed (foil)", not consistent)
    try:
        solve_exact([[Fraction(1), Fraction(2)], [Fraction(2), Fraction(4)]], [Fraction(1), Fraction(2)])
        check("solve_exact: rank deficiency raises", False)
    except ValueError:
        check("solve_exact: rank deficiency raises", True)

    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
