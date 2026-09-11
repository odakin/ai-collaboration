#!/usr/bin/env python3
"""Seeley–DeWitt a4 of Laplace-type operators by numerical invariant fitting (NumPy) — Gilkey's a4 from user-supplied E and Ω on random algebraic curvature tensors, least-squares fit onto an invariant basis, the 1/ε pole map per species, and built-in Dirac + axial torsion / Dirac + U(1) / scalar operators with textbook anchors; --selftest

Layer-1 hoist (2026-09-11) of the heat-kernel engine that a blind referee used to derive, before opening a
manuscript, the logarithmically divergent one-loop action of a Dirac field on a Riemann–Cartan background with
totally antisymmetric contorsion (the instance stays in a private paper repo).  The engine is operator-agnostic:
give it E and Ω for your Laplace-type operator and an invariant basis, and it returns the a4 coefficients.

Pole map (D = 4 − 2ε, total derivatives dropped).  For D = −(∇̃² + E) on a bundle V,
    ln det D |_{1/ε} = −(1/ε) ∫ a4,   a4 = (4π)^{-2} (1/360) tr_V [60 R E + 180 E² + 30 Ω_{μν}Ω^{μν} + (5R² − 2R_{μν}² + 2R_{μνρσ}²) 1]
(Vassilevich, Phys. Rept. 388 (2003) 279, Eqs. (4.26)–(4.28); curvature sign [∇_μ, ∇_ν]V^ρ = R^ρ{}_{σμν}V^σ, R > 0 on spheres).
The Euclidean and Lorentzian effective actions are related as densities by Γ_E = −Γ_M (S_E density = −L_M density), so
    real scalar  Γ_M,div = +(1/2ε) ∫ a4;     Dirac (Γ = −(i/2) ln det(−D̸² + m²), a4 traced over spinors)  Γ_M,div = −(1/2ε) ∫ a4,
with the mass inside E (E ∋ −m²).  External anchors asserted by --selftest (each FAILS under a global sign flip):
    Dirac vacuum energy  L ⊃ −m⁴/(16π²ε) ⇔ V = +m⁴/(16π²ε)   (a fermion loop raises the vacuum energy; a real scalar gives −1/4 of it)
    QED  Γ_M,div = +(e²/12π²ε)(−¼ F_{μν}F^{μν})   (Z₃ − 1 = −e²/12π²ε, screening; same 4/3 as one_loop_pole.py's vacuum polarisation)
    Dirac curvature part = Vassilevich Table 1, spin ½: (a, b, d) = (−7/2, −11, 0);   Dirac log m²R term: δ(M_P²/2) = −m²/(96π²ε)

Dirac with an axial vector, D̸ = γ^μ(∇_μ + iη γ5 S_μ) in dirac_algebra.py conventions (η = −1/4 is minimal coupling for
S^d = ε^{abcd}K_{abc}):
    E = −R/4 − m² + iη γ5 ∇·S − 2η² S²,
    Ω_{μν} = ¼ R_{abμν}γ^aγ^b + iη γ5 (Σ_{νρ}∇_μS^ρ − Σ_{μρ}∇_νS^ρ) − η² [Σ_{μρ}, Σ_{νσ}] S^ρ S^σ,
    (16π²) a4 ⊃ 8η² m² S² + (4/3)η² [∇_μS_ν∇^μS^ν − (∇·S)² + R_{μν}S^μS^ν] = 8η² m² S² + (2/3)η² S_{μν}S^{μν} + t.d.
R S² and (S²)² cancel for every η and there is no (∇·S)² term: the induced axial-torsion kinetic term has the Maxwell
form.  In Shapiro's normalisation (Phys. Rept. 357 (2002) 113, Eq. (3.15): ⅔η²S²_{μν} − 8m²η²S_μS^μ with ε = (4π)²(n−4),
S^ν = ε^{αβμν}T_{αβμ}, minimal η = −1/8, signature (+,−,−,−)) these are the same numbers once prefactor, signature and the
normalisation of S are translated; the absence of the longitudinal term is stated there right below (3.15).  An
evaluation restricted to ∂·S = 0 cannot see that information (physics-verification-cycle.md#referee-side-kernels).
The E/Ω decomposition was checked symbolically in flat space with x-dependent S in the originating instance; here it is
checked end to end by the curvature part (Table 1) and the torsion part (Shapiro) together.

Usage
  from heat_kernel_a4 import fit, dirac_axial_a4, table1_abd, pole_lagrangian
  coeffs, resid = dirac_axial_a4(eta=-0.25)      # {invariant: coefficient of (16π²) a4}
  python3 heat_kernel_a4.py --selftest
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dirac_algebra import ETA, G, G5, I4, Sigma, Sigma_low  # noqa: E402

DIAG = np.diag(ETA)
GG = np.array([[G[a] @ G[b] for b in range(4)] for a in range(4)])            # γ^a γ^b
SL = np.array([[Sigma_low(a, b) for b in range(4)] for a in range(4)])       # Σ_{ab}
SU = np.array([[Sigma(a, b) for b in range(4)] for a in range(4)])           # Σ^{ab}
POLE_FACTOR = {"dirac": -0.5, "real_scalar": 0.5, "complex_scalar": 1.0}     # Γ_M,div = factor · (1/ε) ∫ a4


def raise_index(T, pos):
    """Raise index `pos` of a tensor with the diagonal η."""
    T = np.moveaxis(np.asarray(T), pos, 0)
    T = np.array([DIAG[i] * T[i] for i in range(4)])
    return np.moveaxis(T, 0, pos)


def random_curvature(rng, terms=3):
    """Algebraic curvature tensor R_{abcd} (all lower) as a sum of Kulkarni–Nomizu products of random symmetric matrices."""
    R = np.zeros((4, 4, 4, 4))
    for _ in range(terms):
        h = rng.standard_normal((4, 4)); h = h + h.T
        k = rng.standard_normal((4, 4)); k = k + k.T
        R += (np.einsum("ac,bd->abcd", h, k) + np.einsum("bd,ac->abcd", h, k)
              - np.einsum("ad,bc->abcd", h, k) - np.einsum("bc,ad->abcd", h, k))
    return R


def curvature_scalars(R):
    """Ricci R_{bd} = R^a{}_{bad}, scalar R, R_{μν}R^{μν}, R_{μνρσ}R^{μνρσ}."""
    ric = np.einsum("abad->bd", raise_index(R, 0))
    rs = np.einsum("bb->", raise_index(ric, 0))
    ric2 = np.einsum("ab,ab->", ric, raise_index(raise_index(ric, 0), 1))
    riem2 = np.einsum("abcd,abcd->", R, raise_index(raise_index(raise_index(raise_index(R, 0), 1), 2), 3))
    return ric, rs, ric2, riem2


def tr_omega_squared(Om):
    """tr Ω_{μν} Ω^{μν} for Om[μ, ν] (lower μν)."""
    return sum(DIAG[mu] * DIAG[nu] * np.trace(Om[mu, nu] @ Om[mu, nu]) for mu in range(4) for nu in range(4))


def a4_density_360(E, Om, R=None):
    """360 (4π)² a4 at a point: tr_V[60 R E + 180 E² + 30 Ω²] + dim V (5R² − 2Ric² + 2Riem²)."""
    dim = E.shape[0]
    if R is None:
        rs = ric2 = riem2 = 0.0
    else:
        _, rs, ric2, riem2 = curvature_scalars(R)
    val = 60 * rs * np.trace(E) + 180 * np.trace(E @ E) + 30 * tr_omega_squared(Om) + dim * (5 * rs ** 2 - 2 * ric2 + 2 * riem2)
    return complex(val)


def dirac_axial(R, S, N, m, eta):
    """E and Ω of −D̸² + m² for D̸ = γ^μ(∇_μ + iηγ5S_μ); R all lower, S_a lower, N_{ab} = ∇_a S_b lower."""
    _, rs, _, _ = curvature_scalars(R)
    s_up = DIAG * S
    s2 = S @ s_up
    div_s = np.sum(DIAG * np.diag(N))
    E = (-rs / 4 - m ** 2 - 2 * eta ** 2 * s2) * I4 + 1j * eta * div_s * G5
    n_up2 = N * DIAG[None, :]                                     # ∇_a S^b
    Om = np.zeros((4, 4, 4, 4), dtype=complex)
    for mu, nu in itertools.product(range(4), repeat=2):
        term = 0.25 * np.einsum("ab,abij->ij", R[:, :, mu, nu], GG)
        term = term + 1j * eta * G5 @ (np.einsum("r,rij->ij", n_up2[mu], SL[nu]) - np.einsum("r,rij->ij", n_up2[nu], SL[mu]))
        a_mat = np.einsum("r,rij->ij", s_up, SL[mu])              # Σ_{μρ} S^ρ
        b_mat = np.einsum("s,sij->ij", s_up, SL[nu])              # Σ_{νσ} S^σ
        term = term - eta ** 2 * (a_mat @ b_mat - b_mat @ a_mat)
        Om[mu, nu] = term
    return E, Om


def dirac_u1(F, m, e):
    """Flat space, D̸ = γ^μ(∂_μ + ieA_μ): E = (ie/2) Σ^{μν}F_{μν} − m², Ω_{μν} = ie F_{μν} (F lower, antisymmetric)."""
    E = -m ** 2 * I4 + 0.5j * e * np.einsum("ab,abij->ij", F, SU)
    Om = np.array([[1j * e * F[mu, nu] * I4 for nu in range(4)] for mu in range(4)])
    return E, Om


def real_scalar(R, m, xi):
    """−(□ − ξR − m²): E = −ξR − m² (1×1), Ω = 0."""
    _, rs, _, _ = curvature_scalars(R)
    return np.array([[-xi * rs - m ** 2]], dtype=complex), np.zeros((4, 4, 1, 1), dtype=complex)


DIRAC_AXIAL_KEYS = ("m4", "m2R", "R2", "Ric2", "Riem2", "m2S2", "RS2", "RicSS", "S2sq", "divS2", "NN", "NNT")


def dirac_axial_invariants(R, S, N, m):
    ric, rs, ric2, riem2 = curvature_scalars(R)
    s_up = DIAG * S
    s2 = S @ s_up
    n_up = raise_index(raise_index(N, 0), 1)
    return {"m4": m ** 4, "m2R": m ** 2 * rs, "R2": rs ** 2, "Ric2": ric2, "Riem2": riem2,
            "m2S2": m ** 2 * s2, "RS2": rs * s2, "RicSS": np.einsum("ab,a,b->", ric, s_up, s_up), "S2sq": s2 ** 2,
            "divS2": np.sum(DIAG * np.diag(N)) ** 2, "NN": np.einsum("ab,ab->", N, n_up), "NNT": np.einsum("ab,ba->", N, n_up)}


def fit(sample, keys, n=40, seed=0):
    """Least-squares fit of a sampled scalar onto invariants: sample(rng) -> (value, {key: invariant}). Returns (coeffs, max residual)."""
    rng = np.random.default_rng(seed)
    rows, rhs = [], []
    for _ in range(n):
        value, inv = sample(rng)
        rows.append([inv[k] for k in keys]); rhs.append(value)
    A = np.array(rows, dtype=float); b = np.array(rhs, dtype=complex)
    if np.abs(b.imag).max() > 1e-8:
        raise ValueError("a4 density is not real: check E/Ω")
    coef, *_ = np.linalg.lstsq(A, b.real, rcond=None)
    return dict(zip(keys, coef)), float(np.abs(A @ coef - b.real).max())


def dirac_axial_a4(eta, n=40, seed=0):
    """Coefficients of (16π²) a4 for the Dirac operator with an axial vector (total derivatives dropped)."""
    def sample(rng):
        R = random_curvature(rng)
        S = rng.standard_normal(4); N = rng.standard_normal((4, 4)); m = rng.standard_normal()
        E, Om = dirac_axial(R, S, N, m, eta)
        return a4_density_360(E, Om, R) / 360.0, dirac_axial_invariants(R, S, N, m)
    return fit(sample, DIRAC_AXIAL_KEYS, n=n, seed=seed)


def table1_abd(c_r2, c_ric2, c_riem2):
    """(16π²)a4 ⊃ c_r2 R² + c_ric2 Ric² + c_riem2 Riem²  →  Vassilevich Table 1 (a, b, d), a4 = (2880π²)^{-1}[aC² + b(Ric² − R²/3) + dR² + c□R]."""
    a = 180 * c_riem2
    b = 180 * c_ric2 + 2 * a
    d = 180 * c_r2 - a / 3 + b / 3
    return a, b, d


def pole_lagrangian(coeffs, species):
    """(16π²ε) × Lorentzian pole Lagrangian from the coefficients of (16π²) a4."""
    f = POLE_FACTOR[species]
    return {k: f * v for k, v in coeffs.items()}


def selftest() -> int:
    fails = []

    def near(x, y, msg, tol=1e-8):
        if abs(x - y) > tol:
            fails.append(f"{msg}: {x} vs {y}")

    coeffs, resid = dirac_axial_a4(-0.25)
    near(resid, 0.0, "fit residual (eta = -1/4)", 1e-8)
    expected = {"m4": 2, "m2R": 1 / 3, "R2": 1 / 72, "Ric2": -1 / 45, "Riem2": -7 / 360, "m2S2": 1 / 2, "RS2": 0,
                "RicSS": 1 / 12, "S2sq": 0, "divS2": -1 / 12, "NN": 1 / 12, "NNT": 0}
    for k, v in expected.items():
        near(coeffs[k], v, f"(16π²)a4 coefficient {k} at eta = -1/4")
    a, b, d = table1_abd(coeffs["R2"], coeffs["Ric2"], coeffs["Riem2"])
    near(a, -3.5, "Vassilevich Table 1 spin 1/2: a"); near(b, -11.0, "Table 1: b"); near(d, 0.0, "Table 1: d")
    eta = 0.3
    c2, resid2 = dirac_axial_a4(eta, seed=1)
    near(resid2, 0.0, "fit residual (eta = 0.3)", 1e-8)
    for k, v in {"m2S2": 8 * eta ** 2, "divS2": -4 / 3 * eta ** 2, "NN": 4 / 3 * eta ** 2, "RicSS": 4 / 3 * eta ** 2,
                 "RS2": 0.0, "S2sq": 0.0, "NNT": 0.0}.items():
        near(c2[k], v, f"general-eta coefficient {k}")
    lag = pole_lagrangian(coeffs, "dirac")
    near(lag["m4"], -1.0, "Dirac vacuum energy: (16π²ε) L_m4 = -1 (V = +m^4/16π²ε)")
    near(lag["m2R"], -1 / 6, "Dirac log m²R: delta(M²/2) = -m²/(96π²ε)")
    near(pole_lagrangian({"m4": 0.5}, "real_scalar")["m4"] / lag["m4"], -0.25, "real scalar / Dirac vacuum energy = -1/4")
    rng = np.random.default_rng(7)
    rows, t_e2, t_om2 = [], [], []
    for _ in range(6):
        F = rng.standard_normal((4, 4)); F = F - F.T
        E, Om = dirac_u1(F, 0.0, 1.0)
        f2 = np.einsum("ab,ab->", F, raise_index(raise_index(F, 0), 1))
        t_e2.append(np.trace(E @ E).real / f2); t_om2.append(tr_omega_squared(Om).real / f2)
        rows.append((a4_density_360(E, Om) / 360.0).real / f2)
    for x in t_e2:
        near(x, 2.0, "QED: tr E² = 2 e² F²")
    for x in t_om2:
        near(x, -4.0, "QED: tr Ω² = -4 e² F²")
    for x in rows:
        # (16π²ε) Γ_M = -(1/2) (16π²) a4 = c (−¼ F²)  with c = 4/3 e²  ⇔  Γ_M = (e²/12π²ε)(−¼F²)
        near(POLE_FACTOR["dirac"] * x / (-0.25), 4 / 3, "QED: Z3 coefficient e²/(12π²ε)")
    R = random_curvature(np.random.default_rng(3))
    E, Om = real_scalar(R, 1.3, 1 / 6)
    if np.abs(Om).max() != 0 or E.shape != (1, 1):
        fails.append("real_scalar builder shape")
    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("heat_kernel_a4 selftest: Dirac + axial vector a4 (12 coefficients, general eta), Vassilevich Table 1 spin 1/2, "
          "Dirac vacuum-energy sign and scalar ratio, log m²R, QED Z3 — all PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
