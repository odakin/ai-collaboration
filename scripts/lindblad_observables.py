#!/usr/bin/env python3
"""Finite-matrix Lindblad observable derivatives and post-jump intensity checks; --selftest.

Rates multiply D[L]rho = L rho L† - {L†L,rho}/2. Hamiltonians use hbar=1.
This module evaluates a supplied finite model; it does not certify a Markov
approximation, a density matrix's physical validity, or an infinite-operator
domain. See docs/lindblad-observables.md for cutoff and interpretation limits.
"""
from __future__ import annotations

import argparse
import math
import numpy as np


def _matrix(value):
    result = np.asarray(value, dtype=complex)
    if result.ndim != 2 or result.shape[0] != result.shape[1] or not result.size:
        raise ValueError("expected a nonempty square matrix")
    if not np.isfinite(result).all():
        raise ValueError("matrix entries must be finite")
    return result


def _same_shape(*values):
    arrays = tuple(_matrix(value) for value in values)
    if any(array.shape != arrays[0].shape for array in arrays):
        raise ValueError("matrix dimensions differ")
    return arrays


def _multiply(left, right):
    # Explicit contraction keeps finite-matrix checks independent of BLAS.
    with np.errstate(divide="raise", over="raise", invalid="raise"):
        return np.einsum("ik,kj->ij", left, right, optimize=False)


def _rate(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("rate must be finite and nonnegative")
    return result


def dissipator_adjoint(jump, observable):
    """Return D[jump]† observable, with no rate factor included."""
    jump, observable = _same_shape(jump, observable)
    dagger = jump.conj().T
    number = _multiply(dagger, jump)
    return (_multiply(_multiply(dagger, observable), jump)
            - (_multiply(number, observable) + _multiply(observable, number)) / 2)


def observable_derivative(observable, channels=(), hamiltonian=None):
    """Return the adjoint generator applied to observable.

    channels is an iterable of (nonnegative rate, jump matrix). The full
    result includes i[H,O] when a Hermitian Hamiltonian is supplied.
    """
    observable = _matrix(observable)
    result = np.zeros_like(observable)
    for rate, jump in channels:
        result += _rate(rate) * dissipator_adjoint(jump, observable)
    if hamiltonian is not None:
        hamiltonian, observable = _same_shape(hamiltonian, observable)
        if not np.allclose(hamiltonian, hamiltonian.conj().T):
            raise ValueError("Hamiltonian must be Hermitian")
        result += 1j * (_multiply(hamiltonian, observable)
                       - _multiply(observable, hamiltonian))
    return result


def intensity_derivative_operator(jump, rate=1.0):
    """Derivative of I=rate*<L†L> under that single dissipator alone.

    The operator is rate**2 * L†[L†,L]L. Additional Hamiltonians and
    dissipators require observable_derivative on the intensity observable.
    """
    jump = _matrix(jump)
    dagger = jump.conj().T
    commutator = _multiply(dagger, jump) - _multiply(jump, dagger)
    return _rate(rate)**2 * _multiply(_multiply(dagger, commutator), jump)


def expectation(state, observable):
    """Return Tr(state*observable); no normalization or positivity is imposed."""
    state, observable = _same_shape(state, observable)
    with np.errstate(divide="raise", over="raise", invalid="raise"):
        return np.einsum("ij,ji->", state, observable, optimize=False).item()


def restrict_operator(observable, basis):
    """Return V† O V for an orthonormal column basis V.

    Compute the derivative operator in the full finite model first, then
    restrict it. Projecting jumps before multiplication changes the model.
    """
    observable = _matrix(observable)
    basis = np.asarray(basis, dtype=complex)
    if (basis.ndim != 2 or basis.shape[0] != len(observable)
            or not basis.shape[1] or not np.isfinite(basis).all()):
        raise ValueError("invalid support basis")
    gram = _multiply(basis.conj().T, basis)
    if not np.allclose(gram, np.eye(basis.shape[1])):
        raise ValueError("support basis must have orthonormal columns")
    return _multiply(_multiply(basis.conj().T, observable), basis)


def selftest():
    random = np.random.default_rng(906)
    for dimension in (2, 3, 5):
        def sample():
            return (random.normal(size=(dimension, dimension))
                    + 1j * random.normal(size=(dimension, dimension)))
        jump, raw_state, raw_observable, raw_hamiltonian = [sample() for _ in range(4)]
        state = _multiply(raw_state, raw_state.conj().T)
        state /= np.trace(state)
        observable = raw_observable + raw_observable.conj().T
        hamiltonian = raw_hamiltonian + raw_hamiltonian.conj().T
        rate = 0.7
        number = _multiply(jump.conj().T, jump)
        # A separate primal density derivative checks trace duality.
        primal = rate * (_multiply(_multiply(jump, state), jump.conj().T)
                         - (_multiply(number, state) + _multiply(state, number)) / 2)
        primal -= 1j * (_multiply(hamiltonian, state) - _multiply(state, hamiltonian))
        adjoint = observable_derivative(observable, [(rate, jump)], hamiltonian)
        assert np.allclose(expectation(primal, observable), expectation(state, adjoint))
        sandwich = intensity_derivative_operator(jump, rate)
        direct = observable_derivative(rate * number, [(rate, jump)])
        assert np.allclose(sandwich, direct)
        # Missing an outer lowering operator or rate factor must be detectable.
        wrong = rate**2 * (_multiply(jump.conj().T, jump) - _multiply(jump, jump.conj().T))
        assert not np.allclose(sandwich, wrong)
        assert not np.allclose(sandwich, intensity_derivative_operator(jump, 1.0) * rate)
    lowering = np.diag(np.sqrt(np.arange(1, 4)), 1)
    commutator = _multiply(lowering, lowering.conj().T) - _multiply(lowering.conj().T, lowering)
    support = np.eye(4)[:, :3]
    assert np.allclose(restrict_operator(commutator, support), np.eye(3))
    assert not np.allclose(commutator, np.eye(4))  # finite-cutoff foil
    full = intensity_derivative_operator(lowering)
    assert np.allclose(full, -_multiply(lowering.conj().T, lowering))
    for action in (lambda: _matrix(np.zeros((2, 3))),
                   lambda: _matrix([[float("nan")]]),
                   lambda: intensity_derivative_operator(lowering, -1),
                   lambda: expectation(np.eye(2), np.eye(3)),
                   lambda: restrict_operator(np.eye(2), np.ones((2, 1))),
                   lambda: observable_derivative(np.eye(2), hamiltonian=[[0, 1], [0, 0]])):
        try:
            action()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid input was accepted")
    print("lindblad_observables selftest: duality, sandwich, rate and cutoff foils checked")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
    else:
        parser.print_help()
