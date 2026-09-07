#!/usr/bin/env python3
"""Floquet exponents by monodromy for parametric-resonance claims, with an exact (anharmonic) background (NumPy + SciPy).

Why: narrow-resonance formulas (growth q m/2 at the first Mathieu band, survival q^2 m >~ H) and
"tachyonic" claims about a mode's mass term are cheap to check numerically: integrate the linear
mode equation over one period of the *exact* periodic background and take the largest eigenvalue
of the monodromy matrix.  Two traps this tool is built to expose (both seen in a 2026-09 review):
  * a harmonic-approximation background gives spurious instability to modes that are exactly
    marginal on the true periodic solution (e.g. the k = 0 mode of a field whose mass term comes
    from a conformal rescaling: H = const is an exact solution, so its exponent must vanish);
  * a threshold where the narrow-resonance formulas stop applying is not evidence that a fast
    (broad / tachyonic) resonance starts there.

Built-in models (all with period detected numerically where relevant):
  mathieu      u'' + (A - 2 q cos 2z) u = 0              exponent per unit z; occupation grows at 2 mu
  gauge        (F A')' + F k^2 A = 0, F = 1 + 2 c Phi cos t   (kinetic-function modulation, m = 1)
  conformal    y'' + [k^2 + M(x, xdot)] y = 0 on the exact oscillation of x'' + V'(x) = 0 started at
               rest at amplitude Phi, with M = -(g/2) V'(x) - (g^2/4) xdot^2 (exact Einstein-frame mass
               of a field rescaled by e^{-g x/2}); --linearised drops the xdot^2 term and uses V' -> x.
               Default V = x^2 e^{-gchi x} / 2 (m = 1); any V, dV can be given as numpy expressions in x.

Examples:
  floquet-monodromy.py mathieu --A 1 --q 0.05            # -> mu = q/2 = 0.025
  floquet-monodromy.py gauge --cPhi 0.02 --k 0.5         # -> occupation growth 2 mu = q m/2 with q = 2 c Phi
  floquet-monodromy.py conformal --g 1.0 --Phi 1.46 --k 0 0.25 0.5 0.75 1.0
Selftest: python3 floquet-monodromy.py --selftest
"""
from __future__ import annotations

import argparse
import math
import sys

import numpy as np
from scipy.integrate import solve_ivp


def floquet_exponent(rhs, period, dim=2, rtol=1e-10, atol=1e-12):
    """Largest real part of the Floquet exponents (per unit time) of x' = M(t) x with period `period`."""
    Phi = np.zeros((dim, dim))
    for i in range(dim):
        x0 = np.zeros(dim)
        x0[i] = 1.0
        sol = solve_ivp(rhs, (0.0, period), x0, rtol=rtol, atol=atol, method="DOP853")
        Phi[:, i] = sol.y[:, -1]
    ev = np.linalg.eigvals(Phi)
    return float(np.log(np.max(np.abs(ev))) / period)


def mathieu_exponent(A, q):
    """Mathieu u'' + (A - 2 q cos 2z) u = 0: exponent per unit z (period pi)."""
    return floquet_exponent(lambda z, y: [y[1], -(A - 2 * q * math.cos(2 * z)) * y[0]], math.pi)


def gauge_kinetic_exponent(cPhi, k=0.5, m=1.0):
    """(F A')' + F k^2 A = 0 with F = 1 + 2 c Phi cos(m t); returns amplitude exponent per unit t."""
    def rhs(t, y):
        F = 1 + 2 * cPhi * math.cos(m * t)
        Fd = -2 * cPhi * m * math.sin(m * t)
        return [y[1], -(Fd / F) * y[1] - k * k * y[0]]
    return floquet_exponent(rhs, 2 * math.pi / m)


def make_potential(V_expr=None, dV_expr=None, gchi=0.13):
    """Return (V, dV) callables. Default: V = x^2 exp(-gchi x)/2 so that the curvature at the minimum is 1."""
    if V_expr is None:
        V = lambda x: 0.5 * x * x * math.exp(-gchi * x)
        dV = lambda x: 0.5 * (2 * x - gchi * x * x) * math.exp(-gchi * x)
        return V, dV
    ns = {"np": np, "exp": math.exp, "sin": math.sin, "cos": math.cos, "sqrt": math.sqrt, "tanh": math.tanh, "log": math.log}
    V = eval("lambda x: " + V_expr, ns)
    dV = eval("lambda x: " + dV_expr, ns)
    return V, dV


def periodic_background(dV, Phi, t_max=200.0):
    """Exact oscillation x'' + V'(x) = 0 from rest at x = Phi. Returns (dense solution, period)."""
    def ev(t, y):
        return y[1]
    ev.direction = 1  # velocity crossing zero upward = the left turning point (half period)
    sol = solve_ivp(lambda t, y: [y[1], -dV(y[0])], (0.0, t_max), [Phi, 0.0], events=ev,
                    rtol=1e-11, atol=1e-13, dense_output=True, method="DOP853")
    if len(sol.t_events[0]) == 0:
        raise RuntimeError("no turning point found; increase t_max or check the potential")
    return sol, 2.0 * float(sol.t_events[0][0])


def conformal_mass(g, dV, x, xd, linearised=False):
    """Exact mass term of a field rescaled by e^{-g x/2}: M = -(g/2) V'(x) - (g^2/4) xdot^2."""
    if linearised:
        return -(g / 2.0) * x          # V' -> m^2 x with m = 1, xdot^2 term dropped
    return -(g / 2.0) * dV(x) - (g * g / 4.0) * xd * xd


def conformal_exponents(g, Phi, ks, V_expr=None, dV_expr=None, gchi=0.13, linearised=False):
    V, dV = make_potential(V_expr, dV_expr, gchi)
    sol, T = periodic_background(dV, Phi)
    out = []
    for k in ks:
        def rhs(t, y, k=k):
            x, xd = sol.sol(t)
            return [y[1], -(k * k + conformal_mass(g, dV, x, xd, linearised)) * y[0]]
        out.append(floquet_exponent(rhs, T))
    return T, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("mathieu"); p.add_argument("--A", type=float, default=1.0); p.add_argument("--q", type=float, nargs="+", default=[0.1])
    p = sub.add_parser("gauge"); p.add_argument("--cPhi", type=float, nargs="+", default=[0.02]); p.add_argument("--k", type=float, default=0.5)
    p = sub.add_parser("conformal")
    p.add_argument("--g", type=float, default=1.0, help="conformal parameter gamma (M_P = 1)")
    p.add_argument("--Phi", type=float, default=1.46, help="oscillation amplitude in M_P")
    p.add_argument("--k", type=float, nargs="+", default=[0.0, 0.25, 0.5, 0.75, 1.0])
    p.add_argument("--gchi", type=float, default=0.13)
    p.add_argument("--V", default=None, help="numpy expression in x for V(x) (default x^2 e^{-gchi x}/2)")
    p.add_argument("--dV", default=None, help="expression for V'(x); required with --V")
    p.add_argument("--linearised", action="store_true", help="drop the xdot^2 term and use V' -> x")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd == "mathieu":
        for q in args.q:
            mu = mathieu_exponent(args.A, q)
            print(f"A={args.A} q={q}: mu/z={mu:.6f} (first band centre: q/2={q/2:.6f}); occupation rate in t (z=mt/2): {mu:.6f} m")
    elif args.cmd == "gauge":
        for c in args.cPhi:
            mu = gauge_kinetic_exponent(c, args.k)
            print(f"cPhi={c} k={args.k}: occupation growth 2mu={2*mu:.6f} m; narrow-resonance prediction q m/2 with q=2cPhi -> {c:.6f} m")
    elif args.cmd == "conformal":
        T, mus = conformal_exponents(args.g, args.Phi, args.k, args.V, args.dV, args.gchi, args.linearised)
        print(f"g={args.g} Phi={args.Phi} period={T:.5f} (2pi={2*math.pi:.5f}) q=g*Phi={args.g*args.Phi:.3f} {'linearised' if args.linearised else 'exact mass term'}")
        for k, mu in zip(args.k, mus):
            print(f"  k={k:.3f}: amplitude exponent mu={mu:+.6f} per unit t (occupation rate 2mu={2*mu:+.6f})")
        if not args.linearised and 0.0 in args.k:
            print("  (k = 0 must be marginal on the exact background: H = const is an exact solution)")
    else:
        ap.print_help()
    return 0


def selftest():
    # 1. Mathieu first band centre: mu = q/2 to 1%
    for q in (0.02, 0.05, 0.1):
        mu = mathieu_exponent(1.0, q)
        assert abs(mu - q / 2) < 0.01 * q / 2 + 1e-6, (q, mu)
    # 2. Mathieu A = 0: stable at q = 0.9, unstable at q = 0.95 (first band reaches a = 0 near q = 0.908)
    assert abs(mathieu_exponent(0.0, 0.9)) < 1e-5
    assert mathieu_exponent(0.0, 0.95) > 0.1
    # 3. gauge kinetic function: occupation growth = q m/2 with q = 2 c Phi (2%)
    for c in (0.01, 0.02):
        assert abs(2 * gauge_kinetic_exponent(c, 0.5) - c) < 0.02 * c, c
    # 4. exact background: k = 0 exactly marginal; linearised harmonic-background version is not
    T, mus = conformal_exponents(1.0, 1.46, [0.0, 0.55])
    assert abs(T - 2 * math.pi) < 0.2 and T > 2 * math.pi, T      # anharmonic period slightly longer
    assert abs(mus[0]) < 1e-4, mus                                  # marginal k=0 (integration residual ~1e-6)
    assert mus[1] > 0.2, mus                                        # real instability at finite k (q = 1.46)
    _, lin = conformal_exponents(1.0, 1.46, [0.0], linearised=True)
    assert lin[0] > 0.1, lin                                        # spurious k=0 instability when linearised
    # 5. harmonic potential: period 2 pi to 1e-8 and no instability for uncoupled mode (g = 0)
    _, T0 = periodic_background(lambda x: x, 1.0)
    assert abs(T0 - 2 * math.pi) < 1e-8
    _, zero = conformal_exponents(0.0, 1.0, [0.3], V_expr="0.5*x*x", dV_expr="x")
    assert abs(zero[0]) < 1e-8
    print("selftest OK: Mathieu mu=q/2, a=0 edge at q~0.91, gauge q=2cPhi, exact-background k=0 marginal vs linearised spurious growth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
