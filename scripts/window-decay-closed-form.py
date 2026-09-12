#!/usr/bin/env python3
"""Finite timing window x exponential decay in closed form: the Gaussian-window convolution as an erfc (exponentially modified Gaussian), the threshold where the saddle crosses the window edge, and the universal factor 1/2 there (NumPy + SciPy, --selftest).

WHY THIS EXISTS
---------------
"A finite observation window is applied to a state that decays exponentially" is one
shape that recurs across fields: fluorescence lifetimes read through a Gaussian
instrument response, chromatographic peaks (where the same function is called the
exponentially modified Gaussian), time-resolved resonance response, gated detection of
a decaying source, and amplitudes in which a propagator is integrated against the
timing uncertainty of preparation and detection.

The integral is elementary but easy to get wrong by a factor or a convention, and
papers and proposals frequently quote only a consequence of it -- a threshold, a
suppression factor, a curve in a figure -- without the intermediate step.  Being able
to re-derive the closed form in one call is what lets you check such a quote instead of
believing it.  Two independent reviewers auditing the same figure each rebuilt this
before it was written down once.

THE RESULT
----------
    A(dT) = int_0^inf ds exp(-(G/2 + iE) s) w(s - dT),    w(x) = exp(-x^2 / 2 tau^2)

With kappa = G/2 + iE, completing the square gives the closed form

    A(dT) = exp(kappa^2 tau^2 / 2 - kappa dT) * tau sqrt(pi/2)
            * erfc( -(dT - kappa tau^2) / (sqrt2 tau) )

The saddle sits at s* = dT - kappa tau^2.  Re s* crosses the lower limit s = 0 at

    dT_th = G tau^2 / 2,        n := dT_th / tau = G tau / 2

so a single dimensionless number n -- the decay width measured in units of the window
-- controls how visible the transition is.  Two consequences worth keeping:

  * Normalising the stable-particle (n = 0) plateau to 1, the amplitude at threshold is
    exactly (1/2) exp(-n^2 / 2).  Large n is exponentially suppressed: the state decays
    before the window has resolved it, so no threshold structure survives.
  * For a real decay (E = 0) the ratio of the exact amplitude to its pole (long-time)
    asymptote at threshold is exactly 1/2, for every n, because the erfc argument
    vanishes there: erfc(0) = 1 while erfc(-inf) = 2.  A "factor of two at the
    threshold" in such a figure is this identity, not a fitted feature.
    With an oscillating phase (E != 0) the argument at threshold is imaginary rather
    than zero -- dT_th - kappa tau^2 = -i E tau^2 -- and the ratio becomes
    sqrt(1 + erfi(E tau / sqrt2)^2) / 2, which is >= 1/2 and grows with E tau.  Quoting
    the 1/2 for an oscillating amplitude is the easy mistake here.

The transition is a smooth crossover of width tau centred on dT_th -- never a step.
Any claim of a sharp onset is a claim about a different quantity.

USAGE
-----
  window-decay-closed-form.py --gamma 1e-10 --tau 1e-5          # SI-ish, any units
  window-decay-closed-form.py --n 1.5 --scan -3 6 10            # tabulate J(dT), tau = 1
  window-decay-closed-form.py --n 0 1.5 3 --threshold-table
  window-decay-closed-form.py --selftest

Units are yours: G and tau need only be reciprocal to each other (set hbar = 1, or pass
G in s^-1).  --gamma/--tau and --n are alternative ways to say the same thing.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np

try:
    from scipy.special import erfc as _erfc  # complex-capable
    from scipy.integrate import quad as _quad
except ImportError:  # pragma: no cover - environment dependent
    raise SystemExit("needs SciPy (scipy.special.erfc handles the complex argument)")

SQRT2 = np.sqrt(2.0)


def amplitude(dT, gamma: float, tau: float = 1.0, E: float = 0.0):
    """Closed form of int_0^inf ds exp(-(G/2+iE)s) exp(-(s-dT)^2/2tau^2)."""
    dT = np.asarray(dT, dtype=float)
    kappa = gamma / 2.0 + 1j * E
    z = -(dT - kappa * tau**2) / (SQRT2 * tau)
    return np.exp(kappa**2 * tau**2 / 2.0 - kappa * dT) * tau * np.sqrt(np.pi / 2.0) * _erfc(z)


def amplitude_numeric(dT: float, gamma: float, tau: float = 1.0, E: float = 0.0):
    """Same integral by direct quadrature -- the independent check on the closed form."""
    def integrand(s, imag):
        v = np.exp(-(gamma / 2.0 + 1j * E) * s) * np.exp(-((s - dT) ** 2) / (2 * tau**2))
        return v.imag if imag else v.real
    hi = max(dT, 0.0) + 14 * tau
    re, _ = _quad(integrand, 0.0, hi, args=(False,), limit=500)
    im, _ = _quad(integrand, 0.0, hi, args=(True,), limit=500)
    return re + 1j * im


def pole_asymptote(dT, gamma: float, tau: float = 1.0, E: float = 0.0):
    """Long-time (pole) limit: erfc -> 2, i.e. the plain decaying exponential."""
    dT = np.asarray(dT, dtype=float)
    kappa = gamma / 2.0 + 1j * E
    return np.exp(kappa**2 * tau**2 / 2.0 - kappa * dT) * tau * np.sqrt(2.0 * np.pi)


def threshold(gamma: float, tau: float = 1.0):
    """(dT_th, n) with dT_th = G tau^2 / 2 and n = dT_th / tau = G tau / 2."""
    return gamma * tau**2 / 2.0, gamma * tau / 2.0


def normalised(dT, gamma: float, tau: float = 1.0, E: float = 0.0):
    """|A| with the stable (n=0) long-time plateau normalised to 1."""
    return np.abs(amplitude(dT, gamma, tau, E)) / (tau * np.sqrt(2.0 * np.pi))


def selftest() -> int:
    rng = np.random.default_rng(11)

    # 1. closed form == quadrature, including complex E and dT < 0
    for tau in (0.7, 1.0, 2.3):
        for n in (0.0, 0.4, 1.5, 3.0):
            gamma = 2 * n / tau
            for E in (0.0, 0.3 / tau, 1.7 / tau):
                for dT in (-2.0 * tau, 0.0, n * tau, 1.5 * tau, 4.0 * tau):
                    a = complex(amplitude(dT, gamma, tau, E))
                    b = amplitude_numeric(dT, gamma, tau, E)
                    assert abs(a - b) <= 1e-9 * max(abs(b), 1e-12), (tau, n, E, dT, a, b)

    # 2. threshold bookkeeping
    for tau in (0.5, 1.0, 3.0):
        for gamma in (0.0, 0.8, 4.0):
            dTth, n = threshold(gamma, tau)
            assert np.isclose(dTth, gamma * tau**2 / 2)
            assert np.isclose(n, dTth / tau) and np.isclose(n, gamma * tau / 2)

    # 3. amplitude at threshold is exactly (1/2) exp(-n^2/2) in plateau units (E=0)
    for tau in (0.6, 1.0, 2.0):
        for n in (0.0, 0.5, 1.5, 3.0, 5.0):
            gamma = 2 * n / tau
            dTth, _ = threshold(gamma, tau)
            got = float(normalised(dTth, gamma, tau))
            want = 0.5 * np.exp(-(n**2) / 2.0)
            assert abs(got - want) <= 1e-12 * max(want, 1e-300), (tau, n, got, want)

    # 4. at threshold: exactly 1/2 for a real decay, sqrt(1+erfi(E tau/sqrt2)^2)/2 otherwise
    from scipy.special import erfi as _erfi
    for n in (0.0, 0.7, 2.0, 4.0):
        for tau in (0.8, 1.3):
            gamma = 2 * n / tau
            dTth, _ = threshold(gamma, tau)
            r0 = abs(complex(amplitude(dTth, gamma, tau, 0.0))) / abs(complex(pole_asymptote(dTth, gamma, tau, 0.0)))
            assert abs(r0 - 0.5) < 1e-12, (n, tau, r0)
            for E in (0.4 / tau, 0.9 / tau, 2.0 / tau):
                r = abs(complex(amplitude(dTth, gamma, tau, E))) / abs(complex(pole_asymptote(dTth, gamma, tau, E)))
                want = float(np.sqrt(1.0 + _erfi(E * tau / SQRT2) ** 2) / 2.0)
                assert abs(r - want) < 1e-10, (n, tau, E, r, want)
                assert r >= 0.5 - 1e-12, (n, tau, E, r)

    # 5. limits: deep inside the window -> pole asymptote; far before it -> suppressed
    tau, n = 1.0, 1.2
    gamma = 2 * n / tau
    far = float(np.abs(amplitude(12.0, gamma, tau)) / np.abs(pole_asymptote(12.0, gamma, tau)))
    assert abs(far - 1.0) < 1e-6, far
    assert normalised(-8.0, gamma, tau) < 1e-12

    # 6. n = 0 is the plain Gaussian CDF step of width tau centred on 0
    for dT in (-2.0, -0.5, 0.0, 1.0, 3.0):
        got = float(normalised(dT, 0.0, 1.0))
        want = 0.5 * float(_erfc(-dT / SQRT2).real)
        assert abs(got - want) < 1e-12, (dT, got, want)

    # 7. crossover width is tau, not zero: 10-90% rise spans O(tau), and scales with tau
    for tau in (0.5, 2.0):
        xs = np.linspace(-6 * tau, 6 * tau, 20001)
        ys = normalised(xs, 0.0, tau)
        lo = xs[np.searchsorted(ys, 0.1)]
        hi = xs[np.searchsorted(ys, 0.9)]
        assert 2.0 * tau < (hi - lo) < 2.9 * tau, (tau, hi - lo)

    # 8. random spot-check of the closed form against quadrature
    for _ in range(25):
        tau = float(rng.uniform(0.3, 3.0))
        gamma = float(rng.uniform(0.0, 6.0)) / tau
        E = float(rng.uniform(-2.0, 2.0)) / tau
        dT = float(rng.uniform(-3.0, 6.0)) * tau
        a = complex(amplitude(dT, gamma, tau, E))
        b = amplitude_numeric(dT, gamma, tau, E)
        assert abs(a - b) <= 1e-8 * max(abs(b), 1e-12), (tau, gamma, E, dT, a, b)

    print("selftest OK: closed form vs quadrature, threshold, (1/2)exp(-n^2/2), "
          "1/2 at threshold (real) and its erfi generalisation, limits, crossover width")
    return 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gamma", type=float, help="decay width G (reciprocal to tau)")
    ap.add_argument("--tau", type=float, default=1.0, help="window width (default 1)")
    ap.add_argument("--energy", type=float, default=0.0, help="oscillation frequency E")
    ap.add_argument("--n", type=float, nargs="+", help="give n = G tau / 2 instead of --gamma")
    ap.add_argument("--scan", type=float, nargs=3, metavar=("LO", "HI", "N"),
                    help="tabulate J(dT) over [LO,HI] tau units in N steps")
    ap.add_argument("--threshold-table", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    tau = a.tau
    if a.n is not None:
        ns = a.n
    elif a.gamma is not None:
        ns = [a.gamma * tau / 2.0]
    else:
        ap.error("give --gamma or --n, or --selftest")

    for n in ns:
        gamma = 2.0 * n / tau
        dTth, _ = threshold(gamma, tau)
        print(f"n = {n:g}  (G = {gamma:g}, tau = {tau:g})")
        print(f"  threshold dT_th = G tau^2/2 = {dTth:g}  (= {n:g} tau)")
        print(f"  amplitude at threshold, plateau = 1: {0.5 * np.exp(-n**2 / 2):.6g}"
              f"   [= (1/2) exp(-n^2/2)]")
        print(f"  exact / pole asymptote at threshold: "
              f"{float(np.abs(amplitude(dTth, gamma, tau, a.energy)) / np.abs(pole_asymptote(dTth, gamma, tau, a.energy))):.6f}")
        if a.scan:
            lo, hi, steps = a.scan[0], a.scan[1], int(a.scan[2])
            print("   dT/tau        J (plateau = 1)")
            for dT in np.linspace(lo, hi, steps) * tau:
                print(f"  {dT / tau:8.3f}   {float(normalised(dT, gamma, tau, a.energy)):.6g}")
    if a.threshold_table:
        print("\n     n    (1/2)exp(-n^2/2)   exact/pole at threshold")
        for n in ns:
            gamma = 2.0 * n / tau
            dTth, _ = threshold(gamma, tau)
            r = float(np.abs(amplitude(dTth, gamma, tau)) / np.abs(pole_asymptote(dTth, gamma, tau)))
            print(f"  {n:6g}   {0.5 * np.exp(-n**2 / 2):16.6g}   {r:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
