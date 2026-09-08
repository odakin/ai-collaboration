#!/usr/bin/env python3
"""Zero-mode growth of a spectator field with a dilaton-type coupling e^{-gamma chi/M_P} (d phi)^2 during inflation (NumPy + SciPy only).

Why (2026-09): scientific-computing.md#spectator-check-over-the-roll. A mass estimate at the pivot scale
(m^2 ~ -0.1 gamma H^2) says "light spectator", but the canonical field phi_c = e^{-gamma chi/2 M_P} phi is stretched
by the Weyl factor e^{gamma Delta chi / 2 M_P} over the whole roll (x27 at gamma = 0.7 for Delta chi ~ 9 M_P), and the
mass term at the end of inflation is -(2 gamma + 0.5 gamma^2) H_end^2. The spectator region must be judged over the roll.

What it does (units M_P = 1; potential V = x^p e^{-g x} / 2 with x = chi / M_P):
  1. integrates the exact inflationary background from horizon exit x_* (slow-roll initial velocity) to eps_H = 1;
  2. integrates the canonical zero mode  h'' + 3 H h' + m^2(t) h = 0,  m^2 = -(gamma/2) V'(x) - (gamma^2/4) xdot^2,
     frozen at horizon exit (h = 1, h' = 0), for each gamma;
  3. reports growth h_end / h_*, the Weyl factor e^{gamma (x_* - x_end)/2}, m^2/H^2 at the pivot and at the end,
     and the value at which the field settles, sqrt(|m^2_end| / lambda) H_end, if lambda > 0 (runaway if lambda < 0).

Usage:
  dilaton-spectator-growth.py [--p 2] [--g 0.13] [--xstar 10.4] [--gammas 0.065,0.3,0.7,1,3] [--lam 0.01]
  dilaton-spectator-growth.py --selftest
The selftest pins: x_end = 0.907 for (p, g, x_*) = (2, 0.13, 10.4); growth = 1 at gamma = 0; growth within 2 % of the
Weyl factor at gamma = 0.3 and 0.7; growth monotone in gamma.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from scipy.integrate import solve_ivp


def make_potential(p: float, g: float):
    V = lambda x: 0.5 * x**p * np.exp(-g * x)
    Vp = lambda x: 0.5 * (p * x**(p - 1) - g * x**p) * np.exp(-g * x)
    return V, Vp


def background(p: float, g: float, xstar: float):
    """Exact background from horizon exit to eps_H = 1. Returns (sol, t_end, x_end, xd_end, H_end)."""
    V, Vp = make_potential(p, g)
    H0 = np.sqrt(V(xstar) / 3.0)
    xd0 = -Vp(xstar) / (3.0 * H0)                      # slow-roll velocity at horizon exit

    def rhs(t, y):
        x, xd, N = y
        H = np.sqrt((0.5 * xd**2 + V(x)) / 3.0)
        return [xd, -3.0 * H * xd - Vp(x), H]

    def eps_h_minus_1(t, y):
        x, xd, N = y
        return 0.5 * xd**2 / ((0.5 * xd**2 + V(x)) / 3.0) - 1.0

    eps_h_minus_1.terminal = True
    eps_h_minus_1.direction = 1
    sol = solve_ivp(rhs, (0.0, 1.0e5), [xstar, xd0, 0.0], events=eps_h_minus_1,
                    rtol=1e-10, atol=1e-12, dense_output=True, method="DOP853")
    if len(sol.t_events[0]) == 0:
        raise SystemExit("eps_H = 1 not reached; check p, g, xstar")
    t_end = sol.t_events[0][0]
    x_end, xd_end, _ = sol.sol(t_end)
    H_end = np.sqrt((0.5 * xd_end**2 + V(x_end)) / 3.0)
    return sol, t_end, x_end, xd_end, H_end


def growth(p: float, g: float, xstar: float, gamma: float):
    """Zero-mode growth factor from horizon exit to the end of inflation, plus m^2/H^2 at both ends."""
    V, Vp = make_potential(p, g)
    sol, t_end, x_end, xd_end, H_end = background(p, g, xstar)
    if gamma == 0.0:
        return 1.0, 0.0, 0.0, x_end, H_end

    def rhs(t, y):
        x, xd, _ = sol.sol(t)
        H = np.sqrt((0.5 * xd**2 + V(x)) / 3.0)
        m2 = -(gamma / 2.0) * Vp(x) - (gamma**2 / 4.0) * xd**2
        return [y[1], -3.0 * H * y[1] - m2 * y[0]]

    r = solve_ivp(rhs, (0.0, t_end), [1.0, 0.0], rtol=1e-10, atol=1e-13, method="DOP853")
    x0, xd0, _ = sol.sol(0.0)
    H0 = np.sqrt((0.5 * xd0**2 + V(x0)) / 3.0)
    m2_star = (-(gamma / 2.0) * Vp(x0) - (gamma**2 / 4.0) * xd0**2) / H0**2
    m2_end = (-(gamma / 2.0) * Vp(x_end) - (gamma**2 / 4.0) * xd_end**2) / H_end**2
    return float(r.y[0, -1]), float(m2_star), float(m2_end), float(x_end), float(H_end)


def table(p, g, xstar, gammas, lam):
    sol, t_end, x_end, xd_end, H_end = background(p, g, xstar)
    print(f"background: V = x^{p:g} e^(-{g:g} x)/2, x_* = {xstar:g}; end of inflation (eps_H = 1) at x_end = {x_end:.3f}, "
          f"H_end/H_* = {H_end / np.sqrt(make_potential(p, g)[0](xstar) / 3):.3f}")
    print("  gamma   m^2/H^2 (pivot)   m^2/H^2 (end)   growth h_end/h_*   Weyl e^{gamma dx/2}   settle (lambda>0) / runaway")
    for gm in gammas:
        gr, m2s, m2e, xe, He = growth(p, g, xstar, gm)
        weyl = np.exp(gm * (xstar - xe) / 2.0)
        if m2e < 0:
            fate = f"sqrt(|m2|/lambda) = {np.sqrt(-m2e / lam):.1f} H_end if lambda={lam:g} > 0, runaway if lambda < 0"
        else:
            fate = "positive mass, sits at the origin"
        print(f"  {gm:6.3f}   {m2s:+9.3f}         {m2e:+9.2f}        {gr:10.2f}          {weyl:10.2f}          {fate}")


def selftest() -> int:
    fails = []
    _, _, x_end, _, _ = background(2.0, 0.13, 10.4)
    if abs(x_end - 0.907) > 0.01:
        fails.append(f"x_end = {x_end:.3f}, expected 0.907")
    g0 = growth(2.0, 0.13, 10.4, 0.0)[0]
    if abs(g0 - 1.0) > 1e-9:
        fails.append(f"gamma = 0 growth = {g0}, expected 1")
    prev = 1.0
    for gm in (0.065, 0.3, 0.7):
        gr, m2s, m2e, xe, He = growth(2.0, 0.13, 10.4, gm)
        weyl = np.exp(gm * (10.4 - xe) / 2.0)
        if gm >= 0.3 and abs(gr / weyl - 1.0) > 0.02:
            fails.append(f"gamma = {gm}: growth {gr:.2f} vs Weyl {weyl:.2f} differ by more than 2 %")
        if gr <= prev:
            fails.append(f"growth not monotone at gamma = {gm}")
        prev = gr
        if not (m2s < 0 and m2e < m2s):
            fails.append(f"gamma = {gm}: expected m^2 negative and larger in magnitude at the end ({m2s:.3f}, {m2e:.2f})")
    if fails:
        print("selftest FAIL:\n  " + "\n  ".join(fails))
        return 1
    print("selftest OK (x_end 0.907, gamma=0 flat, growth = Weyl factor within 2 % at 0.3 and 0.7, monotone, mass grows over the roll)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--p", type=float, default=2.0)
    ap.add_argument("--g", type=float, default=0.13)
    ap.add_argument("--xstar", type=float, default=10.4)
    ap.add_argument("--gammas", default="0.065,0.1,0.3,0.5,0.7,1,3")
    ap.add_argument("--lam", type=float, default=0.01)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    table(a.p, a.g, a.xstar, [float(s) for s in a.gammas.split(",")], a.lam)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
