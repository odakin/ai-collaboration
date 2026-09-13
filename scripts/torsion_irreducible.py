#!/usr/bin/env python3
"""Torsion / contorsion irreducible decomposition (trace vector, totally antisymmetric part, mixed part) and the Einstein–Cartan + Holst quadratic forms in the contorsion, with the Immirzi elimination factors (NumPy); --selftest.

Why (2026-09-13): the same index algebra had been re-derived by hand, with a foil, to check printed statements about
torsion in first-order gravity. This module keeps the convention-explicit math, tested, so the next check starts
from it instead of a fresh derivation.

Conventions (all explicit arguments, nothing hidden):
  * contorsion K[a, b, c]: antisymmetric in the frame pair (a, b), c = form index (flat vierbein, frame and
    spacetime indices identified).  Trace vector v_b = g^{ac} K_{abc} (first index with the form index).
  * torsion T[l, m, n]: antisymmetric in the form pair (m, n).  Trace vector v_n = g^{lm} T_{lmn}.
  * totally antisymmetric part = antisymmetrization over the three indices only (weight 1, i.e. X_[abc]).
  * Levi-Civita symbol eps with eps_{01..D-1} = +1 on lower indices; upper indices raised with the metric.
  * curvature K-squared part on a flat vierbein with omega = K:
        F^{ab}_{mn} ⊃ K^a_{c m} K^{cb}_n − (m ↔ n);
    Einstein–Cartan form  EC(K) = e_a^m e_b^n F^{ab}_{mn};  Holst form  H(K) = e_a^m e_b^n eps^{ab}_{kl} F^{kl}_{mn}.
    Holst normalization P^{IJ}_{KL} = delta^[I_K delta^J]_L − eps^{IJ}_{KL}/(2 gamma), i.e. the action density
    EC(K) − H(K)/(2 gamma) (Perez–Rovelli, Freidel–Minic–Takeuchi).

Results (D = 4, Lorentzian, verified in the selftest):
  * decomposition 24 = 4 (trace) + 4 (totally antisymmetric) + 16 (mixed), with
        K_{abc} = K_[abc] + (g_{ac} v_b − g_{bc} v_a)/(D − 1) + q_{abc};
  * EC is block diagonal in (trace, K_[abc], mixed); H couples the trace vector only to K_[abc] (plus mixed–mixed);
  * solving for the trace vector multiplies the K_[abc]-squared coefficient by exactly 1 + 1/gamma^2;
  * eliminating all of K against an axial source A_d eps^{abcd} K_{abc} multiplies the four-fermion coefficient by
    gamma^2/(gamma^2 + 1).
  * torsion (Euclidean): eps^{mnrs} T_{lmn} T^l_{rs} = (4/3) v·S + (mixed–mixed), S^s = eps^{lmns} T_{lmn}; on
    T = dê (a single Fourier mode) it vanishes (total derivative at quadratic order).
The sign of gamma follows the sign convention of eps (flip eps and gamma flips); only gamma^2 enters the factors.

Convention maps (verified in the selftest):
  * weight-1/2 torsion from the contorsion.  With T^a_{mn} := D_[m e^a_n] (brackets of weight 1/2) and
    K^a_{b m} := omega^a_{b m} - Omega(e)^a_{b m} (Levi-Civita part torsion free), T^a_{mn} = K^a_{b[m} e^b_{n]} exactly,
    so with every index converted by the vierbein  T_[lmn] = - K_[lmn]  (contorsion: antisymmetric frame pair first,
    form index last).  torsion_from_contorsion() builds T; the relation is a one-line anchor for any dictionary.
  * index order of the affine connection.  A reference that writes nabla_b A^a = d_b A^a + Gamma^a_{b c} A^c
    (derivative index FIRST) and T^a_{bc} = Gamma^a_{bc} - Gamma^a_{cb} (unit weight) has T_ref = +2 T_ours when
    "ours" has the derivative index LAST (Gamma^l_{n m} = e_a^l D_m e^a_n) and weight 1/2; a reference with unit weight
    and derivative index last has T_ref = -2 T_ours.  A factor of two between a unit-weight and a weight-1/2 torsion
    therefore carries a sign fixed by the index order alone; check it before printing any torsion-contorsion or
    dual-torsion relation that contains such a factor.
    torsion_index_order_map() returns
    both conventions from one connection.
  * form-language Immirzi term.  With the Levi-Civita SYMBOL eps_[mnrs] (+1 on 0123, frame tensor eps_{0123} = +1,
    eps^{0123} = -1 raised with eta), the density (1/4) eps_[mnrs] eta_{ac} eta_{bd} F^{ab}_{mn} e^c_r e^d_s equals
    -(1/4) |e| e_a^m e_b^n eta^{aa'} eta^{bb'} eps_[a'b'cd] F^{cd}_{mn} for ANY vierbein, i.e. -(1/4) of the Holst form.
    Hence adding (m_P^2/gamma) times it to (m_P^2/2) e e F gives the Holst normalization above.  immirzi_form_density()
    and holst_form_general() check this on a random vierbein; flipping the symbol convention flips the map (the sign of
    gamma), which is why a paper should define gamma by printing the Holst form in its own conventions.

Usage:
  python3 torsion_irreducible.py --factors 0.5      # print the two elimination factors for gamma = 0.5
  python3 torsion_irreducible.py --selftest
"""
from __future__ import annotations

import argparse
import itertools
import math
import sys

import numpy as np

LORENTZ4 = np.diag([-1.0, 1.0, 1.0, 1.0])


def levi_civita(D: int) -> np.ndarray:
    """eps with all lower indices, eps_{0..D-1} = +1."""
    e = np.zeros((D,) * D)
    for p in itertools.permutations(range(D)):
        e[p] = np.linalg.det(np.eye(D)[list(p)])
    return e


def raise_all(eps: np.ndarray, metric: np.ndarray) -> np.ndarray:
    gi = np.linalg.inv(metric)
    out = eps
    for axis in range(eps.ndim):
        out = np.moveaxis(np.tensordot(gi, out, axes=([1], [axis])), 0, axis)
    return out


def antisym3(X: np.ndarray) -> np.ndarray:
    return (X + np.transpose(X, (1, 2, 0)) + np.transpose(X, (2, 0, 1))
            - np.transpose(X, (1, 0, 2)) - np.transpose(X, (0, 2, 1)) - np.transpose(X, (2, 1, 0))) / 6.0


# ---------------------------------------------------------------------------- contorsion (frame pair first)
def contorsion_trace_vector(K: np.ndarray, metric: np.ndarray) -> np.ndarray:
    return np.einsum('ac,abc->b', np.linalg.inv(metric), K)


def contorsion_trace_part(K: np.ndarray, metric: np.ndarray) -> np.ndarray:
    D = metric.shape[0]
    v = contorsion_trace_vector(K, metric)
    return (np.einsum('ac,b->abc', metric, v) - np.einsum('bc,a->abc', metric, v)) / (D - 1)


def decompose_contorsion(K: np.ndarray, metric: np.ndarray) -> dict:
    trace = contorsion_trace_part(K, metric)
    axial = antisym3(K)
    return {"trace_vector": contorsion_trace_vector(K, metric), "trace": trace, "axial": axial,
            "mixed": K - axial - trace}


def contorsion_basis(D: int) -> list[np.ndarray]:
    basis = []
    for a in range(D):
        for b in range(a + 1, D):
            for c in range(D):
                B = np.zeros((D, D, D)); B[a, b, c] = 1.0; B[b, a, c] = -1.0; basis.append(B)
    return basis


def projector_ranks(D: int, metric: np.ndarray) -> tuple[int, int, int, int]:
    basis = contorsion_basis(D)
    rank = lambda f: int(np.linalg.matrix_rank(np.array([f(B).ravel() for B in basis])))
    return (rank(lambda X: contorsion_trace_part(X, metric)), rank(antisym3),
            rank(lambda X: decompose_contorsion(X, metric)["mixed"]), len(basis))


# ---------------------------------------------------------------------------- torsion (form pair last)
def torsion_trace_vector(T: np.ndarray, metric: np.ndarray) -> np.ndarray:
    return np.einsum('lm,lmn->n', np.linalg.inv(metric), T)


def torsion_axial_vector(T: np.ndarray, metric: np.ndarray) -> np.ndarray:
    return np.einsum('lmns,lmn->s', raise_all(levi_civita(metric.shape[0]), metric), T)


def torsion_trace_part(T: np.ndarray, metric: np.ndarray) -> np.ndarray:
    D = metric.shape[0]
    v = torsion_trace_vector(T, metric)
    return (np.einsum('lm,n->lmn', metric, v) - np.einsum('ln,m->lmn', metric, v)) / (D - 1)


def parity_odd_torsion_invariant(T1: np.ndarray, T2: np.ndarray, metric: np.ndarray) -> float:
    """eps^{mnrs} T1_{lmn} T2^l_{rs} (D = 4)."""
    eps_up = raise_all(levi_civita(4), metric)
    return float(np.einsum('mnrs,lmn,lk,krs->', eps_up, T1, np.linalg.inv(metric), T2))


# ---------------------------------------------------------------------------- EC + Holst forms (flat vierbein)
def curvature_K2(K: np.ndarray, metric: np.ndarray) -> np.ndarray:
    gi = np.linalg.inv(metric)
    X = np.einsum('acm,cbn->abmn', np.einsum('ai,icm->acm', gi, K), np.einsum('ci,bj,ijn->cbn', gi, gi, K))
    return X - np.swapaxes(X, 2, 3)


def einstein_cartan_form(K: np.ndarray, metric: np.ndarray) -> float:
    return float(np.einsum('abab->', curvature_K2(K, metric)))


def holst_form(K: np.ndarray, metric: np.ndarray, eps_sign: float = 1.0) -> float:
    gi = np.linalg.inv(metric)
    eps_ud = eps_sign * np.einsum('ai,bj,ijkl->abkl', gi, gi, levi_civita(4))
    return float(np.einsum('abkl,klab->', eps_ud, curvature_K2(K, metric)))


def _bilinear(f, X, Y):
    return (f(X + Y) - f(X) - f(Y)) / 2.0


def _subspace(P, basis):
    Y = np.array([P(B).ravel() for B in basis]); _, s, Vt = np.linalg.svd(Y)
    D = basis[0].shape[0]
    return [Vt[i].reshape(D, D, D) for i in range(int((s > 1e-9).sum()))]


def elimination_factors(gamma: float, metric: np.ndarray = LORENTZ4, eps_sign: float = 1.0,
                        holst_denominator: float = 2.0) -> tuple[float, float]:
    """(K_[abc] mass rescaling after solving for the trace vector, four-fermion factor after eliminating all K).

    holst_denominator = 2 is the P = delta delta - eps/(2 gamma) normalization; other values exist only for foils."""
    basis = contorsion_basis(4)
    f = lambda K: einstein_cartan_form(K, metric) - holst_form(K, metric, eps_sign) / (holst_denominator * gamma)
    ec = lambda K: einstein_cartan_form(K, metric)
    V = _subspace(lambda X: contorsion_trace_part(X, metric), basis)
    S = _subspace(antisym3, basis)
    block = lambda g, U, W: np.array([[_bilinear(g, x, y) for y in W] for x in U])
    Mvv, MvS, MSS = block(f, V, V), block(f, V, S), block(f, S, S)
    ratio = np.linalg.solve(block(ec, S, S), MSS - MvS.T @ np.linalg.solve(Mvv, MvS))
    mass = float(np.trace(ratio) / 4.0)
    eps_up = raise_all(levi_civita(4), metric)
    A = np.array([0.3, -1.1, 0.7, 0.5])
    b = np.array([np.einsum('abcd,abc,d->', eps_up, B, A) for B in basis])
    mat = lambda g: np.array([[_bilinear(g, Bi, Bj) for Bj in basis] for Bi in basis])
    c_g = -0.25 * b @ np.linalg.solve(mat(f), b)
    c_inf = -0.25 * b @ np.linalg.solve(mat(ec), b)
    return mass, float(c_g / c_inf)


# ---------------------------------------------------------------------------- convention maps (2026-09-13)
def torsion_from_contorsion(K: np.ndarray, e: np.ndarray, metric: np.ndarray) -> np.ndarray:
    """Weight-1/2 torsion T_{l m n} (all spacetime indices) from the contorsion K_{a b m} (frame pair lower, form index
    last) on a vierbein e[a, m] = e^a_m:  T^a_{mn} = K^a_{b[m} e^b_{n]}, then the frame index converted with e."""
    gi = np.linalg.inv(metric)
    Kud = np.einsum('ac,cbm->abm', gi, K)                                  # K^a_{b m}
    Ta = 0.5 * (np.einsum('abm,bn->amn', Kud, e) - np.einsum('abn,bm->amn', Kud, e))
    return np.einsum('ac,cl,amn->lmn', metric, e, Ta)                      # T_{l m n} = eta_{ac} e^c_l T^a_{mn}


def contorsion_spacetime(K: np.ndarray, e: np.ndarray) -> np.ndarray:
    """K_{l m n} = e^a_l e^b_m K_{a b n} (frame pair converted, form index kept)."""
    return np.einsum('al,bm,abn->lmn', e, e, K)


def torsion_index_order_map(Gamma: np.ndarray) -> dict:
    """From one affine connection written with the derivative index LAST, Gamma[l, n, m] = Gamma^l_{n m} (m = derivative),
    return the torsion in three conventions: ours (weight 1/2, derivative last), a unit-weight reference with the
    derivative index FIRST (Gamma_ref^l_{m n} = Gamma^l_{n m}, T_ref = Gamma_ref^l_{mn} - Gamma_ref^l_{nm}), and a
    unit-weight reference with the derivative index LAST (T = Gamma^l_{mn} - Gamma^l_{nm})."""
    ours = 0.5 * (np.transpose(Gamma, (0, 2, 1)) - Gamma)                  # T^l_{mn} = Gamma^l_{[n m]} (weight 1/2)
    G_first = np.transpose(Gamma, (0, 2, 1))
    return {"ours": ours,
            "unit_derivative_first": G_first - np.transpose(G_first, (0, 2, 1)),
            "unit_derivative_last": Gamma - np.transpose(Gamma, (0, 2, 1))}


def holst_form_general(F: np.ndarray, e: np.ndarray, metric: np.ndarray, symbol_sign: float = 1.0) -> float:
    """|e| e_a^m e_b^n eta^{aa'} eta^{bb'} eps_[a'b'cd] F^{cd}_{mn} for a vierbein e[a, m] and F[a, b, m, n] = F^{ab}_{mn}."""
    gi = np.linalg.inv(metric); einv = np.linalg.inv(e)                    # einv[m, a] = e_a^m
    eps_ud = symbol_sign * np.einsum('ai,bj,ijkl->abkl', gi, gi, levi_civita(4))
    return float(abs(np.linalg.det(e)) * np.einsum('ma,nb,abkl,klmn->', einv, einv, eps_ud, F))


def immirzi_form_density(F: np.ndarray, e: np.ndarray, metric: np.ndarray, symbol_sign: float = 1.0) -> float:
    """(1/4) eps_[mnrs] eta_{ac} eta_{bd} F^{ab}_{mn} e^c_r e^d_s with the Levi-Civita symbol (symbol_sign = +1: +1 on 0123)."""
    F_low = np.einsum('ac,bd,abmn->cdmn', metric, metric, F)
    return float(0.25 * symbol_sign * np.einsum('mnrs,cdmn,cr,ds->', levi_civita(4), F_low, e, e))


# ---------------------------------------------------------------------------- selftest
def selftest() -> int:
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    rng = np.random.default_rng(20260913)
    g = LORENTZ4
    # contorsion decomposition
    A = rng.normal(size=(4, 4, 4)); K = A - np.swapaxes(A, 0, 1)
    d = decompose_contorsion(K, g)
    expect("contorsion: pieces sum to K", np.allclose(d["trace"] + d["axial"] + d["mixed"], K))
    expect("contorsion: trace part reproduces the trace vector",
           np.allclose(contorsion_trace_vector(d["trace"], g), d["trace_vector"]))
    expect("contorsion: axial and mixed parts are traceless",
           np.allclose(contorsion_trace_vector(d["axial"], g), 0) and np.allclose(contorsion_trace_vector(d["mixed"], g), 0))
    expect("contorsion: mixed part has no totally antisymmetric part", np.allclose(antisym3(d["mixed"]), 0))
    expect("contorsion: every piece antisymmetric in the frame pair",
           all(np.allclose(x, -np.swapaxes(x, 0, 1)) for x in (d["trace"], d["axial"], d["mixed"])))
    expect("contorsion ranks D=4: 4 + 4 + 16 = 24", projector_ranks(4, g) == (4, 4, 16, 24))
    D5 = np.diag([-1.0, 1, 1, 1, 1])
    expect("contorsion ranks D=5: D + C(D,3) + rest = D*C(D,2)",
           projector_ranks(5, D5) == (5, math.comb(5, 3), 5 * math.comb(5, 2) - 5 - math.comb(5, 3), 5 * math.comb(5, 2)))
    # torsion parity-odd invariant (Euclidean, as in the source audit)
    E = np.eye(4)
    B = rng.normal(size=(4, 4, 4)); T = B - np.swapaxes(B, 1, 2)
    Tv = torsion_trace_part(T, E); Ta = antisym3(T); Tq = T - Tv - Ta
    v, S = torsion_trace_vector(T, E), torsion_axial_vector(T, E)
    I = lambda X, Y: parity_odd_torsion_invariant(X, Y, E)
    expect("torsion invariant: no trace-trace / axial-axial / trace-mixed / axial-mixed term",
           all(abs(x) < 1e-10 for x in (I(Tv, Tv), I(Ta, Ta), I(Tv, Tq) + I(Tq, Tv), I(Ta, Tq) + I(Tq, Ta))))
    expect("torsion invariant: trace-axial mixing = (4/3) v.S", abs(I(Tv, Ta) + I(Ta, Tv) - 4.0 / 3.0 * (v @ S)) < 1e-10)
    k = rng.normal(size=4); eh = rng.normal(size=(4, 4))
    Tk = np.einsum('m,an->amn', k, eh) - np.einsum('n,am->amn', k, eh)
    expect("torsion invariant: total derivative on T = d e-hat (Fourier mode)", abs(I(Tk, Tk)) < 1e-10)
    # EC + Holst block structure
    basis = contorsion_basis(4)
    V = _subspace(lambda X: contorsion_trace_part(X, g), basis); Sb = _subspace(antisym3, basis)
    Q = _subspace(lambda X: decompose_contorsion(X, g)["mixed"], basis)
    ec = lambda X: einstein_cartan_form(X, g); ho = lambda X: holst_form(X, g)
    blk = lambda f, U, W: abs(np.array([[_bilinear(f, x, y) for y in W] for x in U])).max()
    expect("EC form block diagonal in (trace, axial, mixed)", max(blk(ec, V, Sb), blk(ec, V, Q), blk(ec, Sb, Q)) < 1e-10)
    expect("Holst form couples trace only to axial",
           max(blk(ho, V, V), blk(ho, Sb, Sb), blk(ho, V, Q), blk(ho, Sb, Q)) < 1e-10 and blk(ho, V, Sb) > 1e-6)
    ok_f = True
    for gam in (0.3, 1.0, 2.5, -0.7):
        m, ff = elimination_factors(gam)
        ok_f &= abs(m - (1 + 1 / gam**2)) < 1e-9 and abs(ff - gam**2 / (gam**2 + 1)) < 1e-9
        m2, ff2 = elimination_factors(gam, eps_sign=-1.0)
        ok_f &= abs(m2 - m) < 1e-9 and abs(ff2 - ff) < 1e-9          # only gamma^2 enters
    expect("elimination: mass x (1 + 1/gamma^2), four-fermion x gamma^2/(gamma^2+1), both eps signs", ok_f)
    m_bad, ff_bad = elimination_factors(0.5, holst_denominator=1.0)
    expect("foil: the eps/gamma normalization does not give gamma^2/(gamma^2+1)", abs(ff_bad - 0.2) > 1e-3)
    # convention maps (2026-09-13)
    ok_t = ok_i = True
    for _ in range(3):
        ev = np.eye(4) + 0.3 * rng.normal(size=(4, 4))
        if np.linalg.det(ev) < 0:
            ev[0] *= -1.0
        A2 = rng.normal(size=(4, 4, 4)); K2 = A2 - np.swapaxes(A2, 0, 1)
        T2 = torsion_from_contorsion(K2, ev, g); K2s = contorsion_spacetime(K2, ev)
        ok_t &= np.allclose(antisym3(T2), -antisym3(K2s)) and not np.allclose(antisym3(T2), antisym3(K2s))
        Gm = rng.normal(size=(4, 4, 4)); mp = torsion_index_order_map(Gm)
        ok_t &= np.allclose(mp["unit_derivative_first"], 2 * mp["ours"]) and np.allclose(mp["unit_derivative_last"], -2 * mp["ours"])
        G4 = rng.normal(size=(4, 4, 4, 4)); F = G4 - np.swapaxes(G4, 0, 1); F = F - np.swapaxes(F, 2, 3)
        h = holst_form_general(F, ev, g); scale = max(1.0, abs(h))
        ok_i &= abs(immirzi_form_density(F, ev, g) + h / 4.0) < 1e-10 * scale
        ok_i &= abs(immirzi_form_density(F, ev, g, symbol_sign=-1.0) - h / 4.0) < 1e-10 * scale
    expect("maps: T_[lmn] = -K_[lmn] on a random vierbein; unit-weight torsion = +2 x ours (derivative index first), -2 x ours (last)", ok_t)
    expect("maps: form-language Immirzi density = -(1/4) Holst form on a random vierbein; the opposite symbol sign flips it", ok_i)
    # the Holst form on a flat vierbein agrees with the flat-space holst_form used for the elimination factors
    Kf = rng.normal(size=(4, 4, 4)); Kf = Kf - np.swapaxes(Kf, 0, 1)
    expect("maps: holst_form_general(curvature_K2, flat e) = holst_form",
           abs(holst_form_general(curvature_K2(Kf, g), np.eye(4), g) - holst_form(Kf, g)) < 1e-9 * max(1.0, abs(holst_form(Kf, g))))
    print("selftest:", "ALL PASS" if not failed else "FAILED (" + str(len(failed)) + ")")
    return 0 if not failed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--factors", type=float, metavar="GAMMA")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.factors is not None:
        m, ff = elimination_factors(a.factors)
        print(f"gamma = {a.factors}: K_[abc] mass term x {m:.12g} (1 + 1/gamma^2 = {1 + 1 / a.factors**2:.12g}); "
              f"four-fermion x {ff:.12g} (gamma^2/(gamma^2+1) = {a.factors**2 / (a.factors**2 + 1):.12g})")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
