#!/usr/bin/env python3
"""Binary discrimination certificates, qubit models and foil helpers (NumPy only)."""
from __future__ import annotations

from itertools import product
import sys

import numpy as np

TOL = 2e-10
I2 = np.eye(2)
PAULI = np.array([[[0, 1], [1, 0]], [[0, -1j], [1j, 0]], [[1, 0], [0, -1]]])


def require(test, message):
    if not test:
        raise AssertionError(message)


def close(a, b, message="numerical mismatch"):
    require(np.allclose(a, b, atol=TOL, rtol=TOL), message)


def hermitian(a):
    a = np.asarray(a, dtype=complex)
    require(a.ndim == 2 and a.shape[0] == a.shape[1] and a.shape[0] > 0,
            "expected a nonempty square matrix")
    require(np.isfinite(a).all(), "nonfinite matrix")
    close(a, a.conj().T, "non-Hermitian matrix")
    return a


def tr(a):
    z = np.trace(a)
    require(abs(z.imag) < TOL, "nonreal trace")
    return float(z.real)


def norm1(a):
    """Trace norm, computed from singular values rather than signed eigenvalues."""
    return float(np.linalg.svd(a, compute_uv=False).sum())


def projector(v):
    """Return |v><v|; callers choose normalization (rank-one PSD if v != 0)."""
    v = np.asarray(v, dtype=complex)
    require(v.ndim == 1 and np.isfinite(v).all(), "expected a finite vector")
    return np.outer(v, v.conj())


def random_state(rng, d):
    x = rng.normal(size=(d, d)) + 1j*rng.normal(size=(d, d))
    y = x @ x.conj().T
    return y/tr(y)


def is_psd(a):
    try:
        a = hermitian(a)
    except AssertionError:
        return False
    return bool(np.linalg.eigvalsh(a).min() >= -TOL)


def check_povm(effects):
    effects = [np.asarray(e, dtype=complex) for e in effects]
    require(bool(effects), "empty POVM")
    require(all(is_psd(e) for e in effects), "negative or non-Hermitian POVM effect")
    shape = np.shape(effects[0])
    require(all(np.shape(e) == shape for e in effects), "POVM shape mismatch")
    close(sum(effects), np.eye(shape[0]), "POVM not normalized")


def difference(rho0, rho1, p):
    """Trace-one Hermitian inputs; PSD or GPT membership is a separate obligation."""
    rho0, rho1 = hermitian(rho0), hermitian(rho1)
    require(rho0.shape == rho1.shape, "state shape mismatch")
    require(np.isfinite(p) and 0 <= p <= 1, "prior outside [0, 1]")
    close(tr(rho0), 1, "state 0 not normalized")
    close(tr(rho1), 1, "state 1 not normalized")
    return p*rho0 - (1-p)*rho1


def _pair(x, e):
    x, e = hermitian(x), hermitian(e)
    require(x.shape == e.shape, "effect shape mismatch")
    return x, e


def error(rho0, rho1, p, e):
    """Outcome E guesses state 0; this is a probability only for valid model inputs."""
    x, e = _pair(difference(rho0, rho1, p), e)
    return p - tr(x @ e)


def spectral_bound(x, e):
    """L = (1 - r||X||_1 - (a+b-1)Tr X)/2, with a=min E, b=max E."""
    x, e = _pair(x, e)
    a, b = np.linalg.eigvalsh(e)[[0, -1]]
    return float(.5 - .5*norm1(x)*(b-a) - .5*tr(x)*(b+a-1))


def bounds(rho0, rho1, p, e):
    return spectral_bound(difference(rho0, rho1, p), e)


def slack_terms(x, e):
    """Nonnegative certificate Tr[X_+(bI-E)], Tr[X_-(E-aI)]."""
    x, e = _pair(x, e)
    w, v = np.linalg.eigh(x)
    positive = (v * np.maximum(w, 0)) @ v.conj().T
    negative = (v * np.maximum(-w, 0)) @ v.conj().T
    a, b = np.linalg.eigvalsh(e)[[0, -1]]
    identity = np.eye(len(e))
    return tr(positive @ (b*identity-e)), tr(negative @ (e-a*identity))


def equality_residual(x, e, *, reverse=False):
    """Support-to-extremal-eigenspace residual; reverse=True is a deliberate foil.

    Eigenvalues of X within TOL of zero are ignored: this diagnostic is numerical,
    not an exact rank certificate. Degenerate/zero supports impose no condition.
    """
    x, e = _pair(x, e)
    w, v = np.linalg.eigh(x)
    a, b = np.linalg.eigvalsh(e)[[0, -1]]
    positive, negative = (a, b) if reverse else (b, a)
    return max(np.linalg.norm((e-positive*np.eye(len(e))) @ v[:, w > TOL]),
               np.linalg.norm((e-negative*np.eye(len(e))) @ v[:, w < -TOL]))


def helstrom(rho0, rho1, p):
    """Quantum optimum and one optimal E, including definite-X and zero-mode cases."""
    require(is_psd(rho0) and is_psd(rho1), "Helstrom inputs must be density matrices")
    x = difference(rho0, rho1, p)
    w, v = np.linalg.eigh(x)
    pos = v[:, w > 0]
    return (1-norm1(x))/2, pos @ pos.conj().T


def bloch(r):
    """Trace-one Hermitian Bloch matrix; PSD requires |r| <= 1 separately."""
    r = np.asarray(r)
    require(r.shape == (3,) and np.isrealobj(r) and np.isfinite(r).all(),
            "expected three finite real Bloch coordinates")
    return (I2 + np.einsum('i,ijk->jk', r, PAULI))/2


def qubit_trace_distance(r0, r1, p):
    """Half trace norm of p*rho(r0)-(1-p)*rho(r1), including biased priors."""
    difference(bloch(r0), bloch(r1), p)
    return .5*max(abs(2*p-1), np.linalg.norm(p*np.asarray(r0)-(1-p)*np.asarray(r1)))


def cube_vertices(scale=1.):
    require(np.isfinite(scale) and scale > 0, "cube scale must be positive")
    return [bloch(scale*np.array(v)) for v in product([-1, 1], repeat=3)]


def cube_effect(a, v, scale=1.):
    """Global cube effect certificate: scale*||v||_1 <= min(a, 1-a)."""
    require(np.isfinite(scale) and scale > 0, "cube scale must be positive")
    v = np.asarray(v)
    linear = 2*bloch(v)-I2
    require(np.isfinite(a) and scale*np.abs(v).sum() <= min(a, 1-a)+TOL,
            "not a cube effect")
    return a*I2 + linear


def require_quantum_embedding(states):
    """Checks PSD for the supplied states; covers a polytope iff all vertices given."""
    require(all(is_psd(x) for x in states), "a supplied model state is not PSD")


def depolarizing_map(x, scale):
    """Trace-preserving linear coordinate map; invertible exactly when scale != 0."""
    x = hermitian(x)
    require(np.ndim(scale) == 0 and np.isrealobj(scale) and np.isfinite(scale) and scale != 0,
            "coordinate scale must be a finite nonzero real scalar")
    return scale*x + (1-scale)*tr(x)*np.eye(len(x))/len(x)


def partial_transpose(x, dims=(2, 2)):
    """Transpose subsystem B in the product basis (A-major ordering)."""
    da, db = dims
    require(isinstance(da, int) and isinstance(db, int) and da > 0 and db > 0,
            "invalid bipartite dimensions")
    x = np.asarray(x)
    require(x.shape == (da*db, da*db), "partial transpose shape mismatch")
    return x.reshape(da, db, da, db).transpose(0, 3, 2, 1).reshape(da*db, da*db)


def run(fn):
    try:
        fn()
    except AssertionError as exc:
        print("FAIL:", exc)
        raise SystemExit(1)
    print("PASS:", fn.__module__)


def foil(fn):
    """Accept only an assertion rejection; unexpected exceptions remain failures."""
    try:
        fn()
    except AssertionError as exc:
        print("FOIL-TEETH: rejected:", exc)
        return
    print("FOIL-BROKEN: mutation escaped the checker")
    raise SystemExit(1)


def selftest():
    rng = np.random.default_rng(601)
    count = 0
    for d in (2, 3, 5):
        for p in (0., .03, .5, .91, 1.):
            for _ in range(8):
                r0, r1 = random_state(rng, d), random_state(rng, d)
                y = rng.normal(size=(d, d)) + 1j*rng.normal(size=(d, d))
                e = (y+y.conj().T)/2
                x = difference(r0, r1, p)
                lhs = p*tr(r0@(np.eye(d)-e)) + (1-p)*tr(r1@e)
                close(lhs, error(r0, r1, p, e))
                terms = slack_terms(x, e)
                close(lhs-bounds(r0, r1, p, e), sum(terms))
                require(min(terms) >= -TOL, "negative slack")
                optimum, optimal_e = helstrom(r0, r1, p)
                check_povm([optimal_e, np.eye(d)-optimal_e])
                close(error(r0, r1, p, optimal_e), optimum)
                count += 1
    r0, r1 = np.diag([1., 0]), np.diag([0., 1])
    x = difference(r0, r1, .5)
    close(equality_residual(x, r0), 0)
    require(equality_residual(x, r0, reverse=True) > .9, "reversed support foil escaped")
    close(equality_residual(np.zeros((2, 2)), .4*I2), 0)
    for p in (0., .25, .5, .9, 1.):
        for _ in range(80):
            a, b = rng.uniform(-1, 1, (2, 3))
            close(qubit_trace_distance(a, b, p), norm1(difference(bloch(a), bloch(b), p))/2)
    require(not is_psd([[1, 1], [0, 1]]), "non-Hermitian PSD foil escaped")
    check_povm([[[1, 0], [0, 0]], [[0, 0], [0, 1]]])
    try:
        depolarizing_map(r0, 1j)
    except AssertionError:
        pass
    else:
        raise AssertionError("complex coordinate scale foil escaped")
    require(not is_psd(bloch([1, 1, 1])), "non-PSD cube vertex foil escaped")
    scale = 1/np.sqrt(3)
    require_quantum_embedding(cube_vertices(scale))
    e = cube_effect(.5, [0, 0, .5/scale], scale)
    probabilities = [tr(r@e) for r in cube_vertices(scale)]
    require(min(probabilities) >= -TOL and max(probabilities) <= 1+TOL, "invalid cube effect")
    close(error(bloch([0, 0, scale]), bloch([0, 0, -scale]), .5, e), 0)
    for a, b in ((2, 2), (2, 3)):
        v = rng.normal(size=a) + 1j*rng.normal(size=a)
        w = rng.normal(size=b) + 1j*rng.normal(size=b)
        product_state = projector(np.kron(v, w))
        close(partial_transpose(product_state, (a, b)), projector(np.kron(v, w.conj())))
        close(partial_transpose(partial_transpose(product_state, (a, b)), (a, b)), product_state)
    close(depolarizing_map(depolarizing_map(r0, scale), 1/scale), r0)
    print(f"selftest OK ({count} slack/Helstrom cases; 400 Bloch cases; boundary and mutation certificates)")


if __name__ == "__main__":
    if sys.argv[1:] != ["--selftest"]:
        raise SystemExit("Usage: state_discrimination.py --selftest")
    selftest()
