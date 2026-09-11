#!/usr/bin/env python3
"""Mostly-plus Dirac algebra with asserted conventions (NumPy; exact sympy matrices on request) — γ^a, γ5, ε, σ^{ab}, antisymmetrised products, trace identities and the axial-torsion dictionary; --selftest

Layer-1 hoist (2026-09-11) of the conventions module that a blind referee derivation of a one-loop
Dirac-induced action on a Riemann–Cartan background wrote from scratch (the instance and its checks
stay in a private paper repo).  Sign and factor slips in exactly these identities are the commonest
silent error of one-loop checks; a check that imports them inherits asserted conventions and keeps
only its own freedom.

Conventions (every line is asserted by --selftest):
  η = diag(-1, 1, 1, 1),  {γ^a, γ^b} = 2 η^{ab}
  γ^a = -i γ^a_D, with γ^a_D the Dirac representation of the mostly-minus algebra (Weinberg-type):
      L = -ψ̄ (γ^μ ∂_μ + m) ψ,  ψ̄ = ψ† β,  β = i γ^0,  β² = 1,
      (γ^a)† = -β γ^a β,  (σ^{ab})† = -β σ^{ab} β   (ψ̄γ^aχ is anti-Hermitian-type, ψ̄χ Hermitian-type)
  σ^{ab} = [γ^a, γ^b]/4  (Lorentz generators: D_μ ψ = ∂_μ ψ + ½ ω_{abμ} σ^{ab} ψ),   Σ^{ab} = [γ^a, γ^b]/2 = 2 σ^{ab}
  γ5 = i γ^0 γ^1 γ^2 γ^3,  γ5² = 1;   ε_{0123} = +1 (lower), hence ε^{0123} = -1 and ε^{abcd} ε_{abcd} = -24
  {γ^c, σ^{ab}} = γ^{[cab]};    γ^c σ^{ab} = ½ (γ^{[cab]} + η^{ca} γ^b - η^{cb} γ^a)
  γ^{[abc]} = -i ε^{abcd} γ_d γ5 = +i ε^{abcd} γ5 γ_d            ([...] = antisymmetrisation with weight 1/n!)
  tr γ^a γ^b = 4 η^{ab};  tr γ^a γ^b γ^c γ^d = 4 (η^{ab} η^{cd} - η^{ac} η^{bd} + η^{ad} η^{bc});  tr γ5 γ^a γ^b γ^c γ^d = 4 i ε^{abcd}
  [Σ_{μρ}, Σ_{νσ}] = 2 (η_{ρν} Σ_{μσ} - η_{μν} Σ_{ρσ} - η_{ρσ} Σ_{μν} + η_{μσ} Σ_{ρν})

Axial-torsion dictionary (Lorentzian).  K_{abc} = totally antisymmetric contorsion (ab = Lorentz pair of ω^a{}_b,
c = form index); with T^a = de^a + ω^a{}_b ∧ e^b the unit-weight torsion is T_{abc} = -2 K_{abc}.
  S^d := ε^{abcd} K_{abc}:   S_d S^d = -6 K_{abc} K^{abc}
      (Euclidean signature gives +6: translate S ↔ K in ONE signature, never mix the two dictionaries)
  ½ K_{abc} γ^c σ^{ab} = ¼ K_{abc} γ^{[abc]} = -(i/4) S_d γ^d γ5
  ⇒ the minimally coupled operator is γ^μ(∇_μ + i η γ5 S_μ) with η = -1/4 in this normalisation;
     with S_T^d := ε^{abcd} T_{abc} = -2 S^d the same coupling reads |η_T| = 1/8 (the "minimal" value of the torsion literature).
  Only the totally antisymmetric part of the connection enters a minimally coupled Dirac field ({γ^a, σ^{bc}} is totally antisymmetric).

Usage
  from dirac_algebra import G, G_LOW, G5, ETA, I4, sigma, Sigma, Sigma_low, gamma_antisym, eps_lower, eps_upper
  gam = exact()        # {'G': [sympy.Matrix]*4, 'G5': sympy.Matrix, 'ETA': sympy.Matrix}; entries exactly 0, ±1, ±i
  python3 dirac_algebra.py --selftest
"""
from __future__ import annotations

import itertools
import math
import sys

import numpy as np

ETA = np.diag([-1.0, 1.0, 1.0, 1.0])
I4 = np.eye(4, dtype=complex)
_I2 = np.eye(2, dtype=complex)
_Z2 = np.zeros((2, 2), dtype=complex)
_PAULI = (
    np.array([[0, 1], [1, 0]], dtype=complex),
    np.array([[0, -1j], [1j, 0]], dtype=complex),
    np.array([[1, 0], [0, -1]], dtype=complex),
)
_GAMMA_D = [np.block([[_I2, _Z2], [_Z2, -_I2]])] + [np.block([[_Z2, s], [-s, _Z2]]) for s in _PAULI]
G = [-1j * g for g in _GAMMA_D]                   # γ^a, upper index, mostly plus
G_LOW = [ETA[a, a] * G[a] for a in range(4)]      # γ_a
G5 = 1j * G[0] @ G[1] @ G[2] @ G[3]
BETA = 1j * G[0]


def perm_sign(p) -> int:
    """Sign of a permutation given as a sequence of distinct comparable items."""
    p = list(p)
    s = 1
    for i in range(len(p)):
        for j in range(i + 1, len(p)):
            if p[i] > p[j]:
                s = -s
    return s


def eps_lower(a, b, c, d) -> int:
    """ε_{abcd} with ε_{0123} = +1."""
    idx = (a, b, c, d)
    if len(set(idx)) < 4:
        return 0
    return perm_sign(idx)


def eps_upper(a, b, c, d) -> float:
    """ε^{abcd} = η^{aa'} η^{bb'} η^{cc'} η^{dd'} ε_{a'b'c'd'}  (so ε^{0123} = -1)."""
    return eps_lower(a, b, c, d) * ETA[a, a] * ETA[b, b] * ETA[c, c] * ETA[d, d]


def sigma(a, b):
    """σ^{ab} = [γ^a, γ^b]/4 (upper indices)."""
    return (G[a] @ G[b] - G[b] @ G[a]) / 4


def Sigma(a, b):
    """Σ^{ab} = [γ^a, γ^b]/2 = 2 σ^{ab} (upper indices)."""
    return (G[a] @ G[b] - G[b] @ G[a]) / 2


def Sigma_low(a, b):
    """Σ_{ab} (both indices lowered with η)."""
    return ETA[a, a] * ETA[b, b] * Sigma(a, b)


def gamma_antisym(*idx):
    """γ^{[a1 … an]} with weight 1/n! (upper indices)."""
    out = np.zeros((4, 4), dtype=complex)
    for p in itertools.permutations(range(len(idx))):
        prod = I4
        for i in p:
            prod = prod @ G[idx[i]]
        out = out + perm_sign(p) * prod
    return out / math.factorial(len(idx))


def axial_vector_from_contorsion(K):
    """S^d = ε^{abcd} K_{abc} (upper d) for a totally antisymmetric K with all indices lower."""
    K = np.asarray(K)
    S = np.zeros(4, dtype=complex if np.iscomplexobj(K) else float)
    for a, b, c, d in itertools.permutations(range(4), 4):
        S[d] += eps_upper(a, b, c, d) * K[a, b, c]
    return S


def exact():
    """Exact sympy versions {'G': [γ^a], 'G5': γ5, 'ETA': η}; entries are built as integers + i·integers (no nsimplify)."""
    import sympy as sp

    def conv(M):
        rows = []
        for i in range(4):
            row = []
            for j in range(4):
                z = complex(M[i, j])
                re, im = round(z.real), round(z.imag)
                if abs(z.real - re) > 1e-12 or abs(z.imag - im) > 1e-12:
                    raise ValueError("gamma entry is not a Gaussian integer")
                row.append(sp.Integer(re) + sp.I * sp.Integer(im))
            rows.append(row)
        return sp.Matrix(rows)

    return {"G": [conv(g) for g in G], "G5": conv(G5), "ETA": sp.diag(-1, 1, 1, 1)}


def _random_three_form(rng):
    """A totally antisymmetric K_{abc} (4 independent components)."""
    base = rng.standard_normal(4)
    K = np.zeros((4, 4, 4))
    for a, b, c in itertools.permutations(range(4), 3):
        d = ({0, 1, 2, 3} - {a, b, c}).pop()
        K[a, b, c] = perm_sign((a, b, c, d)) * base[d]
    return K


def checks() -> list:
    """Return the list of failed identities (empty = all conventions hold)."""
    fails = []

    def ok(cond, msg):
        if not cond:
            fails.append(msg)

    ok(all(np.allclose(G[a] @ G[b] + G[b] @ G[a], 2 * ETA[a, b] * I4) for a in range(4) for b in range(4)), "Clifford")
    ok(np.allclose(BETA @ BETA, I4), "beta^2 = 1")
    ok(all(np.allclose(G[a].conj().T, -BETA @ G[a] @ BETA) for a in range(4)), "(g^a)^+ = -beta g^a beta")
    ok(all(np.allclose(sigma(a, b).conj().T, -BETA @ sigma(a, b) @ BETA) for a in range(4) for b in range(4)), "(sigma)^+ = -beta sigma beta")
    ok(np.allclose(G5 @ G5, I4), "gamma5^2 = 1")
    ok(all(np.allclose(G5 @ G[a] + G[a] @ G5, 0) for a in range(4)), "{gamma5, g^a} = 0")
    ok(sum(eps_upper(*i) * eps_lower(*i) for i in itertools.product(range(4), repeat=4)) == -24, "eps^abcd eps_abcd = -24")
    ok(eps_upper(0, 1, 2, 3) == -1, "eps^0123 = -1")
    for a, b, c in itertools.product(range(4), repeat=3):
        g3 = gamma_antisym(c, a, b)
        ok(np.allclose(G[c] @ sigma(a, b) + sigma(a, b) @ G[c], g3), f"{{g^c, sigma^ab}} = g^[cab] at {a}{b}{c}")
        ok(np.allclose(G[c] @ sigma(a, b), 0.5 * (g3 + ETA[c, a] * G[b] - ETA[c, b] * G[a])), f"g^c sigma^ab split at {a}{b}{c}")
    for a, b, c in itertools.permutations(range(4), 3):
        g3 = gamma_antisym(a, b, c)
        ok(np.allclose(g3, -1j * sum(eps_upper(a, b, c, d) * G_LOW[d] @ G5 for d in range(4))), f"g^[abc] = -i eps g_d g5 at {a}{b}{c}")
        ok(np.allclose(g3, 1j * sum(eps_upper(a, b, c, d) * G5 @ G_LOW[d] for d in range(4))), f"g^[abc] = +i eps g5 g_d at {a}{b}{c}")
    ok(all(np.isclose(np.trace(G[a] @ G[b]), 4 * ETA[a, b]) for a in range(4) for b in range(4)), "tr gg")
    for a, b, c, d in itertools.product(range(4), repeat=4):
        ok(np.isclose(np.trace(G[a] @ G[b] @ G[c] @ G[d]),
                      4 * (ETA[a, b] * ETA[c, d] - ETA[a, c] * ETA[b, d] + ETA[a, d] * ETA[b, c])), "tr gggg")
        ok(np.isclose(np.trace(G5 @ G[a] @ G[b] @ G[c] @ G[d]), 4j * eps_upper(a, b, c, d)), "tr g5 gggg = 4i eps")
    for m, r, n, s in itertools.product(range(4), repeat=4):
        lhs = Sigma_low(m, r) @ Sigma_low(n, s) - Sigma_low(n, s) @ Sigma_low(m, r)
        rhs = 2 * (ETA[r, n] * Sigma_low(m, s) - ETA[m, n] * Sigma_low(r, s)
                   - ETA[r, s] * Sigma_low(m, n) + ETA[m, s] * Sigma_low(r, n))
        ok(np.allclose(lhs, rhs), "[Sigma, Sigma] algebra")
    rng = np.random.default_rng(20260911)
    K = _random_three_form(rng)
    S_up = axial_vector_from_contorsion(K)
    S_low = ETA @ S_up
    K_up = np.einsum("abc,a,b,c->abc", K, np.diag(ETA), np.diag(ETA), np.diag(ETA))
    ok(np.isclose(S_low @ S_up, -6 * np.einsum("abc,abc->", K, K_up)), "S.S = -6 K.K (Lorentzian)")
    coupling = sum(0.5 * K[a, b, c] * G[c] @ sigma(a, b) for a, b, c in itertools.product(range(4), repeat=3))
    ok(np.allclose(coupling, -0.25j * sum(S_low[d] * G[d] @ G5 for d in range(4))), "1/2 K g sigma = -(i/4) S g g5")
    gam = exact()
    ok(all(np.allclose(np.array(gam["G"][a].evalf(), dtype=complex), G[a]) for a in range(4)), "exact() matches numeric")
    return fails


def selftest() -> int:
    fails = checks()
    if fails:
        for f in sorted(set(fails)):
            print("FAIL", f)
        return 1
    print("dirac_algebra selftest: Clifford, hermiticity, gamma5, epsilon, sigma products, traces, Sigma algebra, "
          "axial-torsion dictionary, exact matrices — all PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
