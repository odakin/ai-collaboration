#!/usr/bin/env python3
"""Domain counterexamples and weighted half-line Green algebra; --selftest.

The checks show two reusable traps.  Membership in the separate product
domains does not by itself justify differentiating an unbounded conjugation,
and a weak commutator on a maximal differential domain does not make that
realization symmetric or its expectation real.  Analytic endpoint arguments
remain separate from this symbolic/finite-sum anchor.
"""
from __future__ import annotations

import argparse

import numpy as np
import sympy as sp


def membership_counterexample(projection_vector=(1, -2, 1)):
    base = sp.Matrix([1, 1, 1])
    hamiltonian = sp.diag(0, 1, 2)
    direction = sp.Matrix(projection_vector)
    projection = direction * direction.T / (direction.T * direction)[0]
    assert projection * projection == projection
    assert projection == projection.T
    assert projection * base == sp.zeros(3, 1)
    assert projection * hamiltonian * base == sp.zeros(3, 1)
    assert hamiltonian * projection * base == sp.zeros(3, 1)
    phase = sp.symbols("z")
    translated = sp.Matrix([1, phase, phase**2])
    target = sp.Matrix([1, -2, 1]) * (1 - phase) ** 2 / 6
    assert sp.simplify(projection * translated - target) == sp.zeros(3, 1)
    step = sp.symbols("s", positive=True)
    cosine_series = lambda x: sp.pi**2 / 6 - sp.pi * x / 2 + x**2 / 4
    series = sp.expand(
        (3 * cosine_series(0) - 4 * cosine_series(step)
         + cosine_series(2 * step)) / 8
    )
    norm_squared = sp.simplify(sp.Rational(8, 3) * series / step**2)
    assert norm_squared == sp.pi / (3 * step)
    indices = np.arange(1, 200001, dtype=float)
    for value in (0.2, 0.1, 0.05):
        numeric = 8 / (3 * value**2) * np.sum(
            np.sin(indices * value / 2) ** 4 / indices**2
        )
        assert abs(numeric / (np.pi / (3 * value)) - 1) < 1e-3


def weighted_green_identity(ordering=sp.Rational(1, 2)):
    energy = sp.symbols("E", positive=True)
    weight = sp.Function("b")(energy)
    bar_phi = sp.Function("F")(energy)
    psi = sp.Function("G")(energy)
    bar_t_phi = sp.I * (
        weight * sp.diff(bar_phi, energy)
        + ordering * sp.diff(weight, energy) * bar_phi
    )
    t_psi = -sp.I * (
        weight * sp.diff(psi, energy)
        + ordering * sp.diff(weight, energy) * psi
    )
    actual = bar_t_phi * energy * psi - energy * bar_phi * t_psi
    expected = sp.I * energy * sp.diff(weight * bar_phi * psi, energy)
    assert sp.simplify(actual - expected) == 0


def maximum_domain_warning():
    energy = sp.symbols("E", positive=True)
    state = sp.sqrt(2) * sp.exp(-energy)
    time_state = -sp.I * sp.diff(state, energy)
    h_state = energy * state
    integrate = lambda expression: sp.integrate(expression, (energy, 0, sp.oo))
    mean_time = integrate(state * time_state)
    weak = integrate(sp.conjugate(time_state) * h_state
                     - sp.conjugate(h_state) * time_state)
    assert mean_time == sp.I and weak == -sp.I and state.subs(energy, 0) != 0


def selftest():
    membership_counterexample()
    weighted_green_identity()
    maximum_domain_warning()
    for foil in (
        lambda: membership_counterexample((1, -1, 1)),
        lambda: weighted_green_identity(sp.Integer(0)),
    ):
        try:
            foil()
        except AssertionError:
            continue
        raise AssertionError("deliberately broken domain/ordering input was accepted")
    print("selftest OK: membership counterexample, Green identity, maximal-domain warning, 2 foils")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if not args.selftest:
        parser.error("use --selftest or import the module")
    selftest()
