#!/usr/bin/env python3
"""Linear growth of daughter-field modes in an expanding oscillating-inflaton background, with the time at which
the vacuum is imposed as an explicit knob (NumPy + SciPy only).

Why: "the resonance completes at coupling X" is a statement about how many e-folds of occupation a mode gains
before the expansion redshifts the resonance parameter q ~ a^{-3/2} below unity.  That number depends on (a) the
exact background (eps_H = 1 is not eps_V = 1: for x^2 e^{-0.13 x} the end-of-inflation energy differs by 1.9 and
the "onset" amplitude Phi by 1.4), (b) where the vacuum is imposed (end of inflation vs a few e-folds earlier,
when a tachyonic mass term is already amplifying sub-horizon modes), and (c) which modes are counted (k/a at
the start must exceed H for a Bunch-Davies start to mean anything).  This tool integrates the background in
cosmic time from slow roll through the oscillations and the linear mode equation for a set of comoving k, and
reports max_k ln n_k at successive oscillations for several vacuum-imposition points.  Second occurrence of the
same need in two blind reviews (2026-09) -> promoted to a shared tool.

Units: M_P = 1, m_chi = 1 (V = f(x)/f''(0) so that V''(0) = 1), x = chi/M_P.
Mode:  h'' + 3 H h' + [k^2/a^2 + M(x, xdot)] h = 0, default M = -(g/2) V'(x) - (g^2/4) xdot^2
       (exact Einstein-frame mass of a field rescaled by e^{-g x/2}; any numpy expression in x, xd, g via --M).
Growth measure: n_k = (|pi_c|^2 + (k/a)^2 |h_c|^2) / (2 k/a) - 1/2 with h_c = a^{3/2} h (massless-limit
       occupation, equal to the adiabatic one once the mass term is negligible; well defined while M < 0).

Examples:
  expanding-mode-growth.py --g 10 --start end --start eps_V=1 --start x=3 --osc 10
  expanding-mode-growth.py --g 0.7 --k 0.3 0.5 1.0 --osc 20
Selftest: expanding-mode-growth.py --selftest
"""
from __future__ import annotations

import argparse
import math
import sys

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq


class Model:
    def __init__(self, fexpr="x**2*exp(-gchi*x)", params=None, Mexpr=None):
        self.params = {"gchi": 0.13}; self.params.update(params or {})
        self.fexpr = fexpr
        self.Mexpr = Mexpr or "-(g/2)*dV - (g**2/4)*xd**2"
        self.norm = self._f2(0.0)
    def _f_raw(self, x):
        env = dict(np.__dict__); env.update(self.params); env["x"] = x
        return eval(self.fexpr, {"__builtins__": {}}, env)
    def _f2(self, x, h=1e-3):
        return (self._f_raw(x + h) - 2 * self._f_raw(x) + self._f_raw(x - h)) / h**2
    def V(self, x):  return self._f_raw(x) / self.norm            # V''(0) = 1  (m = 1, V = x^2/2 near 0)
    def dV(self, x, h=1e-5): return (self.V(x + h) - self.V(x - h)) / (2 * h)
    def M(self, g, x, xd):
        env = dict(np.__dict__); env.update(self.params); env.update(dict(g=g, x=x, xd=xd, V=self.V(x), dV=self.dV(x)))
        return eval(self.Mexpr, {"__builtins__": {}}, env)


def background(model, x0=3.0, tmax=400.0):
    V, dV = model.V, model.dV
    H0 = math.sqrt(V(x0) / 3); xd0 = -dV(x0) / (3 * H0)
    def rhs(t, y):
        x, xd, lna = y; H = math.sqrt((0.5 * xd * xd + V(x)) / 3.0)
        return [xd, -3 * H * xd - dV(x), H]
    def end_inf(t, y):
        x, xd, lna = y; return xd * xd / (2 * (0.5 * xd * xd + V(x)) / 3.0) - 1.0
    end_inf.direction = 1
    sol = solve_ivp(rhs, [0, tmax], [x0, xd0, 0.0], events=end_inf, rtol=1e-10, atol=1e-12, dense_output=True, max_step=0.05)
    return sol, float(sol.t_events[0][0])


def start_time(model, sol, t_end, spec):
    if spec == "end":
        return t_end
    if spec.startswith("eps_V="):
        target = float(spec[6:])
        def epsV(t): x = sol.sol(t)[0]; return 0.5 * (model.dV(x) / model.V(x))**2 - target
        return brentq(epsV, 0.0, t_end)
    if spec.startswith("x="):
        xt = float(spec[2:])
        return brentq(lambda t: sol.sol(t)[0] - xt, 0.0, t_end)
    raise SystemExit(f"unknown --start {spec}")


def run_modes(model, g, ks, t_start, t_stop, sol, a_ref):
    x0, xd0, lna0 = sol.sol(t_start); a0 = math.exp(lna0) / a_ref
    m2 = model.M(g, x0, xd0)
    w2 = ks**2 / a0**2 + m2
    w0 = np.sqrt(np.where(w2 > 0, w2, ks**2 / a0**2))
    H0 = math.sqrt((0.5 * xd0 * xd0 + model.V(x0)) / 3.0)
    h0 = 1.0 / np.sqrt(2 * w0 * a0**3) + 0j; hd0 = (-1j * w0 - 1.5 * H0) * h0
    nk = len(ks)
    y0 = np.concatenate([[x0, xd0, lna0], h0.real, h0.imag, hd0.real, hd0.imag])
    def rhs(t, y):
        x, xd, lna = y[0], y[1], y[2]; a = math.exp(lna) / a_ref
        H = math.sqrt((0.5 * xd * xd + model.V(x)) / 3.0); m2 = model.M(g, x, xd)
        hr, hi, hdr, hdi = y[3:3 + nk], y[3 + nk:3 + 2 * nk], y[3 + 2 * nk:3 + 3 * nk], y[3 + 3 * nk:]
        W2 = ks**2 / a**2 + m2
        return np.concatenate([[xd, -3 * H * xd - model.dV(x), H], hdr, hdi, -3 * H * hdr - W2 * hr, -3 * H * hdi - W2 * hi])
    t_eval = np.arange(t_start, t_stop, 2 * math.pi)
    s = solve_ivp(rhs, [t_start, t_stop], y0, t_eval=t_eval, rtol=1e-9, atol=1e-14, method="DOP853")
    out = []
    for i, t in enumerate(s.t):
        y = s.y[:, i]; x, xd, lna = y[0], y[1], y[2]; a = math.exp(lna) / a_ref
        H = math.sqrt((0.5 * xd * xd + model.V(x)) / 3.0)
        h = y[3:3 + nk] + 1j * y[3 + nk:3 + 2 * nk]; hd = y[3 + 2 * nk:3 + 3 * nk] + 1j * y[3 + 3 * nk:]
        hc = a**1.5 * h; pc = a**1.5 * (hd + 1.5 * H * h); wk = ks / a
        n = (np.abs(pc)**2 + wk**2 * np.abs(hc)**2) / (2 * wk) - 0.5
        q = abs(g) * math.sqrt(2 * (0.5 * xd * xd + model.V(x)))      # = g * Phi_equiv (m = 1, M_P = 1)
        out.append(dict(osc=(t - t_stop) / (2 * math.pi), t=t, a=a, H=H, q=q, lnn=np.log(np.maximum(n, 1e-300))))
    return out


def report(model, g, ks, starts, n_osc, kmin):
    sol, t_end = background(model)
    a_ref = math.exp(sol.sol(t_end)[2])
    xe, xde, _ = sol.sol(t_end)
    print(f"end of inflation (eps_H=1): x={xe:.3f}, H={math.sqrt((0.5*xde**2+model.V(xe))/3):.3f} m, Phi_equiv={math.sqrt(2*(0.5*xde**2+model.V(xe))):.2f} M_P")
    sel = ks >= kmin
    for st in starts:
        ts = start_time(model, sol, t_end, st)
        x0, xd0, lna0 = sol.sol(ts); H0 = math.sqrt((0.5 * xd0**2 + model.V(x0)) / 3)
        out = run_modes(model, g, ks, ts, t_end + 2 * math.pi * n_osc, sol, a_ref)
        # oscillation index relative to t_end
        row = []
        for o in out:
            j = (o["t"] - t_end) / (2 * math.pi)
            ln = o["lnn"][sel]; i = int(np.argmax(ln))
            row.append((j, ln[i], ks[sel][i], o["q"]))
        s = "  ".join(f"osc{j:5.1f}: {v:5.1f} (k={k:.2f}, q={q:.2f})" for j, v, k, q in row if j >= -0.01)
        print(f"start {st:>10} (x={x0:.3f}, H={H0:.3f} m, {sol.sol(t_end)[2]-lna0:.2f} e-folds before end; k/a_start >= {kmin/math.exp(lna0-sol.sol(t_end)[2]):.2f} m): g={g}: max_k ln n | {s}")


def selftest():
    model = Model()
    sol, t_end = background(model)
    xe = sol.sol(t_end)[0]
    assert abs(xe - 0.907) < 0.01, xe                          # exact eps_H = 1 for x^2 e^{-0.13 x}
    a_ref = math.exp(sol.sol(t_end)[2]); ks = np.array([0.5, 1.0])
    out0 = run_modes(model, 0.0, ks, t_end, t_end + 2 * math.pi * 5, sol, a_ref)
    assert np.all(out0[-1]["lnn"] < 0.5), out0[-1]["lnn"]                  # no coupling -> no growth (n stays < 1)
    out1 = run_modes(model, 1.0, ks, t_end, t_end + 2 * math.pi * 5, sol, a_ref)
    out3 = run_modes(model, 3.0, ks, t_end, t_end + 2 * math.pi * 5, sol, a_ref)
    assert out3[-1]["lnn"].max() > out1[-1]["lnn"].max() > out0[-1]["lnn"].max(), (out1[-1]["lnn"], out3[-1]["lnn"])
    tV = start_time(model, sol, t_end, "eps_V=1"); assert 0 < t_end - tV < 2.0, (tV, t_end)
    print("selftest OK (x_end 0.907, g=0 flat, growth monotone in g, eps_V=1 start earlier than eps_H=1)")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--g", type=float, default=10.0)
    ap.add_argument("--f", default="x**2*exp(-gchi*x)"); ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--M", default=None, help="mass term numpy expression in x, xd, g, V, dV")
    ap.add_argument("--k", type=float, nargs="+", default=list(np.concatenate([np.linspace(0.02, 0.5, 7), np.linspace(0.6, 3.0, 13)])))
    ap.add_argument("--kmin", type=float, default=0.0, help="report only modes with comoving k >= kmin (a_end = 1)")
    ap.add_argument("--start", action="append", default=[], help="end | eps_V=1 | x=3.0  (repeatable)")
    ap.add_argument("--osc", type=int, default=10)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest: return selftest()
    params = {k: float(v) for k, v in (p.split("=") for p in a.param)}
    model = Model(a.f, params, a.M)
    report(model, a.g, np.array(sorted(a.k)), a.start or ["end"], a.osc, a.kmin)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
