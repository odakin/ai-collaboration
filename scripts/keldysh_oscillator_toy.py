#!/usr/bin/env python3
"""Three coupled oscillators with time-dependent frequencies and a cubic coupling: mode functions, Schrödinger-evolved wavefunction coefficients, vertex integrals and truncated Fock operators, for checking in-in (Schwinger–Keldysh) and wavefunction-coefficient identities in a model where both sides are computable; --selftest.

Why (layer-1 hoist, measured once): claims such as "the +- one-loop amplitude equals an integral of psi3(t1) psi3*(t2)",
"the equal-time purity loss is 2 Re F_{+-} per real degree of freedom" or "the opposite-branch vertex carries sign X"
fix signs, factors of 2 and complex conjugations that a continuum calculation hides.  Three real oscillators q, k, p
(p plays k' = |k+q|) with H = sum (p_i^2 + w_i(t)^2 x_i^2)/2 + g(t) x_q x_k x_p give independent access to
  * mode functions u_i: u'' + w^2 u = 0, u(t0) = 1/sqrt(2 w), u'(t0) = -i w u(t0)  (Wronskian u u'* - u* u' = i);
  * wavefunction coefficients from the Schrödinger equation for Psi = exp(-1/2 sum psi2_i x_i^2 - psi3 x_q x_k x_p):
        psi2_i' = -i (psi2_i^2 - w_i^2),   psi3' = -i (psi2_q + psi2_k + psi2_p) psi3 + i g(t);
  * vertex integrals J(t) = ∫_{t0}^t g u_q u_k u_p and Jc(t) = ∫ g u_q* u_k* u_p*;
  * truncated Fock operators to build x_i(t) = u_i a_i + u_i* a_i^† and evolve states exactly.
A frequency bump creates Bogoliubov mixing (an excited environment after the bump).  Default parameters are synthetic.
Limits: non-derivative coupling only; distinct modes; no superhorizon hierarchy (so it cannot test statements that rely
on retarded << Wightman).  Rules: conventions/physics-verification-cycle.md kernel 26 (#definition-level-judge).
"""
import sys

import numpy as np
from scipy.integrate import solve_ivp

LBL = ("q", "k", "p")


def bump_frequencies(w0=None, amp=0.8, width=1.2):
    w0 = w0 or {"q": 0.3, "k": 2.0, "p": 2.3}
    return lambda lbl, t: w0[lbl] * (1.0 + amp * np.exp(-(t / width) ** 2))


def smooth_coupling(g0=1.0):
    return lambda t: g0 * np.exp(-((t + 4.0) / 6.0) ** 2) + g0 * 0.5 * (1 + np.tanh((t - 2.0) / 2.0)) * np.exp(-((t - 12.0) / 14.0) ** 2)


class Toy:
    def __init__(self, omega=None, g=None, t0=-30.0, t1=30.0):
        self.omega = omega or bump_frequencies()
        self.g = g or smooth_coupling()
        self.t0, self.t1 = t0, t1

    def _rhs(self, t, y):
        out = np.zeros_like(y)
        us, ps2 = {}, {}
        for i, l in enumerate(LBL):
            o = 6 * i
            u, up, p2 = y[o] + 1j * y[o + 1], y[o + 2] + 1j * y[o + 3], y[o + 4] + 1j * y[o + 5]
            w2 = self.omega(l, t) ** 2
            upp, dp2 = -w2 * u, -1j * (p2 * p2 - w2)
            out[o], out[o + 1], out[o + 2], out[o + 3] = up.real, up.imag, upp.real, upp.imag
            out[o + 4], out[o + 5] = dp2.real, dp2.imag
            us[l], ps2[l] = u, p2
        gt = self.g(t)
        J = gt * us["q"] * us["k"] * us["p"]
        Jc = gt * np.conj(us["q"] * us["k"] * us["p"])
        psi3 = y[22] + 1j * y[23]
        d3 = -1j * (ps2["q"] + ps2["k"] + ps2["p"]) * psi3 + 1j * gt
        out[18], out[19], out[20], out[21], out[22], out[23] = J.real, J.imag, Jc.real, Jc.imag, d3.real, d3.imag
        return out

    def solve(self, tmax=None, rtol=1e-12, atol=1e-14):
        y0 = np.zeros(24)
        for i, l in enumerate(LBL):
            o = 6 * i
            w = self.omega(l, self.t0)
            u = 1 / np.sqrt(2 * w)
            up = -1j * w * u
            y0[o], y0[o + 1], y0[o + 2], y0[o + 3], y0[o + 4] = u.real, u.imag, up.real, up.imag, w
        return solve_ivp(self._rhs, (self.t0, tmax if tmax is not None else self.t1), y0, method="DOP853",
                         rtol=rtol, atol=atol, dense_output=True)

    @staticmethod
    def unpack(sol, t):
        y = sol.sol(t)
        d = {}
        for i, l in enumerate(LBL):
            o = 6 * i
            d["u" + l], d["du" + l], d["psi2" + l] = y[o] + 1j * y[o + 1], y[o + 2] + 1j * y[o + 3], y[o + 4] + 1j * y[o + 5]
        d["J"], d["Jc"], d["psi3"] = y[18] + 1j * y[19], y[20] + 1j * y[21], y[22] + 1j * y[23]
        return d


def fock_ops(nmax=4):
    a1 = np.diag(np.sqrt(np.arange(1, nmax + 1)), 1)
    eye = np.eye(nmax + 1)
    A = {"q": np.kron(np.kron(a1, eye), eye), "k": np.kron(np.kron(eye, a1), eye), "p": np.kron(np.kron(eye, eye), a1)}
    vac = np.zeros((nmax + 1) ** 3, dtype=complex)
    vac[0] = 1.0
    return A, vac


def xop(A, lbl, u):
    """Heisenberg-picture free field x(t) = u a + u* a^† in the truncated Fock space."""
    return u * A[lbl] + np.conj(u) * A[lbl].conj().T


def selftest() -> None:
    toy = Toy()
    sol = toy.solve()
    for t in (-10.0, 0.0, 17.0):
        d = Toy.unpack(sol, t)
        for l in LBL:
            wr = d["u" + l] * np.conj(d["du" + l]) - np.conj(d["u" + l]) * d["du" + l]
            assert abs(wr - 1j) < 1e-8, (t, l, wr)                                   # Wronskian
            assert abs(d["psi2" + l] - (-1j * np.conj(d["du" + l]) / np.conj(d["u" + l]))) < 1e-7   # psi2 = -i u*'/u*
        prod_uc = np.conj(d["uq"] * d["uk"] * d["up"])
        assert abs(d["psi3"] - 1j * d["Jc"] / prod_uc) < 1e-6 * max(1.0, abs(d["psi3"]))  # tree relation psi3 = i Jc / prod u*
    A, vac = fock_ops(3)
    u = 0.4 - 0.2j
    x = xop(A, "q", u)
    assert np.allclose(x, x.conj().T)
    comm = A["q"] @ A["q"].conj().T - A["q"].conj().T @ A["q"]
    assert abs((vac.conj() @ comm @ vac) - 1) < 1e-12
    print("keldysh_oscillator_toy selftest: PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        print(__doc__)
