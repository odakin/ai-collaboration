#!/usr/bin/env python3
"""N_* fixed point for single-field inflation with a given reheating history, exact-background observables, and
history-separation metrics in the (n_s, r) plane (NumPy + SciPy only).

Why: "reheating temperature -> number of e-folds at the pivot -> (n_s, r)" is where a reheating claim meets
the CMB, and the chain of conventions (entropy-conservation constant, w = 0 between the end of inflation and
rho_rh, V_0 from A_s, the inflaton mass fed back into the decay rate) is easy to get subtly wrong.  This tool
does the chain from scratch so a reviewer or an author can reproduce a table of (T_rh, N_*, n_s, r) and the
"separation at fixed r / at fixed n_s" between two histories without touching the paper's own code.
Second occurrence of the same need in two blind reviews (2026-09) -> promoted to a shared tool.

Model:  V(chi) = V0 * f(x), x = chi/M_P, with f given as a numpy expression in x (parameters via --param).
        The field rolls toward smaller x; the end of inflation is eps_V = 1 (LO) and eps_H = 1 (exact background).
        m_chi = sqrt(V0 f''(0)) / M_P (quadratic minimum at x = 0).
Reheating: --Trh T (GeV), or --gamma-coeff C meaning Gamma = C * m_chi^3 / M_P^2 (GeV), or --instantaneous.
N_*:    N_* = C0 + (1/4) ln(V_*^2 / (M_P^4 rho_end)) + (1/12) ln(rho_rh / rho_end) - (1/12) ln g_*,
        C0 = -ln(k_*/a0H0) + ln(T0/H0) + (1/3) ln g_s0 - (1/4) ln(30/pi^2) - (1/2) ln 3   (= 61.49 for H0 = 67.4)
        solved as a fixed point with V0 from A_s = V_*/(24 pi^2 eps_V M_P^4) and m_chi fed back into Gamma.
Observables: LO potential slow roll, and second-order Hubble-flow (Stewart-Lyth) on the exact background
        integrated in e-folds (the point N_* e-folds before eps_H = 1).

Examples:
  nstar-fixed-point.py --f "x**2*exp(-g*x)" --param g=0.13 --instantaneous
  nstar-fixed-point.py --f "x**2*exp(-g*x)" --param g=0.13 --gamma-coeff 4.87e-3     # Gamma = gdH^2/(32 pi) m^3/M_P^2, gdH=0.7
  nstar-fixed-point.py --f "x**2*exp(-g*x)" --scan g 0.05 0.25 41 --gamma-coeff 4.87e-3 --out traj.csv
  nstar-fixed-point.py --separation trajA.csv trajB.csv        # Delta n_s at fixed r, r ratio at fixed n_s
Selftest: nstar-fixed-point.py --selftest
"""
from __future__ import annotations

import argparse
import math
import sys

import numpy as np
from scipy.integrate import quad, solve_ivp
from scipy.optimize import brentq

MP_DEFAULT = 2.4e18
C_SL = 0.5772156649015329 + math.log(2.0) - 2.0     # Stewart-Lyth constant


def nstar_constant(H0_kms=67.4, T0_K=2.7255, gs0=3.91, kstar=0.05):
    H0_Mpc = H0_kms / 299792.458
    T0 = T0_K * 8.617333262e-5 * 1e-9
    H0_GeV = H0_kms * 1e3 / 3.0857e22 * 6.582119569e-25
    return -math.log(kstar / H0_Mpc) + math.log(T0 / H0_GeV) + math.log(gs0) / 3 - 0.25 * math.log(30 / math.pi**2) - 0.5 * math.log(3.0)


class Potential:
    """f(x) from a numpy expression; derivatives by finite differences (step scaled to x)."""
    def __init__(self, expr, params):
        self.expr, self.params = expr, dict(params)
    def f(self, x):
        env = dict(np.__dict__); env.update(self.params); env["x"] = x
        return eval(self.expr, {"__builtins__": {}}, env)
    def d1(self, x, h=1e-4):
        return (self.f(x + h) - self.f(x - h)) / (2 * h)
    def d2(self, x, h=1e-3):
        return (self.f(x + h) - 2 * self.f(x) + self.f(x - h)) / h**2
    def eps(self, x):  return 0.5 * (self.d1(x) / self.f(x))**2
    def eta(self, x):  return self.d2(x) / self.f(x)
    def x_end(self, lo, hi):
        return brentq(lambda x: self.eps(x) - 1.0, lo, hi)
    def N_of_x(self, xs, xe):
        return quad(lambda x: self.f(x) / self.d1(x), xe, xs)[0]
    def x_of_N(self, N, xe, hi):
        return brentq(lambda x: self.N_of_x(x, xe) - N, xe * (1 + 1e-6), hi)


def fixed_point(pot, xe, hi, As, gstar, MP, C0, Trh=None, gamma_coeff=None, instantaneous=False, N0=55.0, tol=1e-7):
    N = N0
    for _ in range(100):
        xs = pot.x_of_N(N, xe, hi)
        e = pot.eps(xs)
        V0 = As * 24 * math.pi**2 * e * MP**4 / pot.f(xs)
        Vs = V0 * pot.f(xs)
        m = math.sqrt(V0 * pot.d2(0.0)) / MP
        rho_end = 1.5 * V0 * pot.f(xe)             # eps = 1: kinetic = V/2
        if instantaneous:
            rho_rh, T = rho_end, None
        else:
            T = Trh if Trh is not None else (90 / (math.pi**2 * gstar))**0.25 * math.sqrt(gamma_coeff * m**3 / MP**2 * MP)
            rho_rh = math.pi**2 / 30 * gstar * T**4
        Nn = C0 + 0.25 * math.log(Vs**2 / (MP**4 * rho_end)) + math.log(rho_rh / rho_end) / 12 - math.log(gstar) / 12
        if abs(Nn - N) < tol:
            N = Nn; break
        N = 0.5 * (N + Nn)
    xs = pot.x_of_N(N, xe, hi); e = pot.eps(xs); eta = pot.eta(xs)
    return dict(N=N, xs=xs, V0=V0, m=m, Trh=T, rho_rh=rho_rh, rho_end=rho_end, ns_LO=1 - 6 * e + 2 * eta, r_LO=16 * e)


def exact_observables(pot, xs_lo, N_star, x0_margin=4.0, hi_cap=None):
    """Integrate x(N) exactly from slow roll x0 > xs; return HFF and 2nd-order (n_s, r) at N_star before eps_H = 1."""
    f, d1 = pot.f, pot.d1
    x0 = xs_lo + x0_margin if hi_cap is None else min(xs_lo + x0_margin, hi_cap)
    def rhs(N, y):
        x, xp = y
        H2 = f(x) / (3 - xp**2 / 2)
        return [xp, -(3 - xp**2 / 2) * xp - d1(x) / H2]
    def end(N, y): return y[1]**2 / 2 - 1.0
    end.terminal = True; end.direction = 1
    sol = solve_ivp(rhs, [0, 500], [x0, -d1(x0) / f(x0)], events=end, rtol=1e-10, atol=1e-12, dense_output=True, max_step=0.05)
    Ne = sol.t_events[0][0]
    def hff(Nq):
        x, xp = sol.sol(Nq); e1 = xp**2 / 2; H2 = f(x) / (3 - e1)
        xpp = -(3 - e1) * xp - d1(x) / H2
        return x, e1, 2 * xpp / xp, H2
    Nx = Ne - N_star
    x, e1, e2, H2 = hff(Nx)
    dN = 1e-3
    e3 = (math.log(abs(hff(Nx + dN)[2])) - math.log(abs(hff(Nx - dN)[2]))) / (2 * dN)
    ns = 1 - 2 * e1 - e2 - 2 * e1**2 - (2 * C_SL + 3) * e1 * e2 - C_SL * e2 * e3
    r = 16 * e1 * (1 + C_SL * e2)
    x_end_exact = sol.sol(Ne)[0]
    return dict(x=x, eps1=e1, eps2=e2, eps3=e3, ns=ns, r=r, x_end_exact=x_end_exact, N_from_x0=Ne)


def run_one(args, params):
    pot = Potential(args.f, params)
    lo, hi = args.xend_bracket
    xe = pot.x_end(lo, hi)
    fp = fixed_point(pot, xe, args.x_hi, args.As, args.gstar, args.MP, nstar_constant(args.H0), Trh=args.Trh,
                     gamma_coeff=args.gamma_coeff, instantaneous=args.instantaneous)
    ex = exact_observables(pot, fp["xs"], fp["N"], hi_cap=args.x_hi)
    return fp, ex


def separation(fileA, fileB, r_grid=(0.03, 0.035, 0.04, 0.045), ns_grid=(0.955, 0.958, 0.960)):
    from scipy.interpolate import interp1d
    A = np.loadtxt(fileA, delimiter=",", skiprows=1); B = np.loadtxt(fileB, delimiter=",", skiprows=1)
    def col(T, name): return T[:, {"p": 0, "N": 1, "ns": 2, "r": 3}[name]]
    fA = interp1d(col(A, "r"), col(A, "ns")); fB = interp1d(col(B, "r"), col(B, "ns"))
    gA = interp1d(col(A, "ns"), col(A, "r")); gB = interp1d(col(B, "ns"), col(B, "r"))
    print("fixed r: n_s(A) - n_s(B)")
    for rr in r_grid:
        try: print(f"  r={rr}: {float(fA(rr)) - float(fB(rr)):+.4f}")
        except ValueError: print(f"  r={rr}: out of range")
    print("fixed n_s: r(A)/r(B)")
    for nn in ns_grid:
        try: print(f"  ns={nn}: {float(gA(nn)) / float(gB(nn)):.2f}")
        except ValueError: print(f"  ns={nn}: out of range")


def selftest():
    C0 = nstar_constant()
    assert abs(C0 - 61.49) < 0.02, C0
    pot = Potential("x**2*exp(-g*x)", {"g": 0.13})
    xe = pot.x_end(0.5, 5.0); assert abs(xe - 1.295) < 0.002, xe
    inst = fixed_point(pot, xe, 2 / 0.13 - 1e-3, 2.1e-9, 106.75, MP_DEFAULT, C0, instantaneous=True)
    assert abs(inst["N"] - 56.5) < 0.2 and abs(inst["ns_LO"] - 0.9611) < 0.001 and abs(inst["r_LO"] - 0.0273) < 0.0005, inst
    ex = exact_observables(pot, inst["xs"], inst["N"], hi_cap=2 / 0.13 - 1e-3)
    assert abs(ex["ns"] - inst["ns_LO"]) < 0.0005 and abs(ex["r"] - inst["r_LO"]) < 0.0005, ex   # 2nd order vs LO
    assert abs(ex["x_end_exact"] - 0.907) < 0.01, ex["x_end_exact"]                                 # eps_H = 1 differs from eps_V = 1
    pert = fixed_point(pot, xe, 2 / 0.13 - 1e-3, 2.1e-9, 106.75, MP_DEFAULT, C0, gamma_coeff=0.7**2 / (32 * math.pi))
    assert 51.5 < pert["N"] < 52.2 and 1.5e9 < pert["Trh"] < 3e9, pert                               # slower reheating -> fewer e-folds
    assert pert["ns_LO"] < inst["ns_LO"] and pert["r_LO"] > inst["r_LO"]
    print("selftest OK (constant 61.49, x_end LO/exact, instantaneous vs perturbative ordering, 2nd order = LO to 5e-4)")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--f", default="x**2*exp(-g*x)", help="f(x) numpy expression, V = V0 f(chi/M_P)")
    ap.add_argument("--param", action="append", default=[], help="name=value (repeatable)")
    ap.add_argument("--scan", nargs=4, metavar=("NAME", "LO", "HI", "N"), help="scan one parameter, write CSV (--out)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--Trh", type=float); ap.add_argument("--gamma-coeff", type=float); ap.add_argument("--instantaneous", action="store_true")
    ap.add_argument("--As", type=float, default=2.1e-9); ap.add_argument("--gstar", type=float, default=106.75)
    ap.add_argument("--MP", type=float, default=MP_DEFAULT); ap.add_argument("--H0", type=float, default=67.4)
    ap.add_argument("--xend-bracket", type=float, nargs=2, default=(0.3, 5.0)); ap.add_argument("--x-hi", type=float, default=15.0)
    ap.add_argument("--separation", nargs=2, metavar=("A.csv", "B.csv"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest: return selftest()
    if a.separation: separation(*a.separation); return 0
    params = {k: float(v) for k, v in (p.split("=") for p in a.param)}
    if not (a.Trh or a.gamma_coeff or a.instantaneous): ap.error("give --Trh, --gamma-coeff or --instantaneous")
    if a.scan:
        name, lo, hi, n = a.scan[0], float(a.scan[1]), float(a.scan[2]), int(a.scan[3])
        rows = []
        for v in np.linspace(lo, hi, n):
            params[name] = v
            fp, ex = run_one(a, params)
            rows.append((v, fp["N"], ex["ns"], ex["r"]))
            print(f"{name}={v:.4f}: N*={fp['N']:.2f} ns={ex['ns']:.4f} r={ex['r']:.4f} Trh={fp['Trh']}")
        if a.out:
            np.savetxt(a.out, np.array(rows), delimiter=",", header=f"{name},Nstar,ns,r", comments="")
        return 0
    fp, ex = run_one(a, params)
    print(f"N_* constant = {nstar_constant(a.H0):.3f}")
    print(f"T_rh = {fp['Trh']}, N_* = {fp['N']:.3f}, x_* = {fp['xs']:.4f}, m_chi = {fp['m']:.3e} GeV, V0^(1/4) = {fp['V0']**0.25:.3e} GeV")
    print(f"LO: n_s = {fp['ns_LO']:.4f}, r = {fp['r_LO']:.4f};  exact background + 2nd-order HFF: n_s = {ex['ns']:.4f}, r = {ex['r']:.4f}")
    print(f"end of inflation: x(eps_V=1) = {pot_end(a, params):.4f}, x(eps_H=1) = {ex['x_end_exact']:.4f}")
    return 0


def pot_end(a, params):
    return Potential(a.f, params).x_end(*a.xend_bracket)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
