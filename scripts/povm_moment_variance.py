#!/usr/bin/env python3
"""Finite-POVM measured moments, first-operator variance and noise; --selftest.

The reusable distinction is M_2 versus M_1 squared.  The measured variance is
Tr(rho M_2)-Tr(rho M_1)^2, while the norm-form variance of the first moment is
Tr(rho M_1^2)-Tr(rho M_1)^2.  Their difference is the POVM noise.  Finite
matrices test this algebra and coupling scaling, not unbounded domains.
"""
from __future__ import annotations

import argparse

import numpy as np

TOL = 2e-11


def _hermitian(matrix, name):
    matrix = np.asarray(matrix, dtype=complex)
    assert matrix.ndim == 2 and matrix.shape[0] == matrix.shape[1], name
    assert np.allclose(matrix, matrix.conj().T, atol=TOL, rtol=TOL), name
    return matrix


def validate_povm(effects):
    effects = [_hermitian(effect, "effect") for effect in effects]
    assert effects
    dimension = effects[0].shape[0]
    assert all(effect.shape == (dimension, dimension) for effect in effects)
    assert all(np.linalg.eigvalsh(effect).min() >= -TOL for effect in effects)
    assert np.allclose(sum(effects), np.eye(dimension), atol=TOL, rtol=TOL)
    return effects


def validate_state(state):
    state = _hermitian(state, "state")
    assert np.linalg.eigvalsh(state).min() >= -TOL
    assert np.isclose(np.trace(state), 1, atol=TOL, rtol=TOL)
    return state


def moment_operator(effects, outcomes, order):
    effects = validate_povm(effects)
    outcomes = np.asarray(outcomes, dtype=float)
    assert outcomes.shape == (len(effects),)
    return sum(outcome**order * effect for outcome, effect in zip(outcomes, effects))


def expectation(state, operator):
    value = np.trace(validate_state(state) @ _hermitian(operator, "operator"))
    assert abs(value.imag) < TOL
    return float(value.real)


def variance_decomposition(effects, outcomes, state):
    first = moment_operator(effects, outcomes, 1)
    second = moment_operator(effects, outcomes, 2)
    mean = expectation(state, first)
    measured = expectation(state, second) - mean**2
    intrinsic = expectation(state, first @ first) - mean**2
    noise = expectation(state, second - first @ first)
    assert measured >= -TOL and intrinsic >= -TOL and noise >= -TOL
    assert np.isclose(measured, intrinsic + noise, atol=TOL, rtol=TOL)
    return {"mean": mean, "measured_variance": measured,
            "first_operator_variance": intrinsic, "noise": noise}


def _example(scale):
    a = np.array([[1.0, 0.0], [0.0, 0.0]])
    b = np.ones((2, 2)) / 2
    effects = [np.eye(2) - scale * (a + b), scale * a, scale * b]
    outcomes = [0, 1, 3]
    vector = np.array([1, 1j]) / np.sqrt(2)
    state = np.outer(vector, vector.conj())
    return effects, outcomes, state


def selftest():
    rows = []
    for scale in (0.1, 0.01, 0.001):
        row = variance_decomposition(*_example(scale))
        assert np.isclose(row["first_operator_variance"] / scale**2, 2.5)
        assert np.isclose(row["measured_variance"] / scale, 5 - 4 * scale)
        assert np.isclose(np.sqrt(row["measured_variance"])**2,
                          row["measured_variance"])
        rows.append(row)
    assert rows[1]["measured_variance"] / rows[0]["measured_variance"] > 0.09
    assert rows[1]["first_operator_variance"] / rows[0]["first_operator_variance"] < 0.011
    try:
        wrong_standard_deviation = rows[0]["measured_variance"]
        assert np.isclose(wrong_standard_deviation**2,
                          rows[0]["measured_variance"])
    except AssertionError:
        pass
    else:
        raise AssertionError("variance was accepted as a standard deviation")
    print("selftest OK: M2/M1^2 split, positive noise, scaling, and square-root foil")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if not args.selftest:
        parser.error("use --selftest or import the module")
    selftest()
