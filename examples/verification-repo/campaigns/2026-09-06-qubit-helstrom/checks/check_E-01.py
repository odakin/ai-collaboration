#!/usr/bin/env python3
"""E-01: qubit Helstrom bound in Bloch form, checked from the definition of the optimum.

Definition used: Err(M) = p Tr rho0 M1 + (1-p) Tr rho1 M0 over POVMs {M0, M1 = I - M0}, 0 <= M0 <= I.
Claim: min_M Err = 1/2 - 1/2 * max(|2p-1|, |p r0 - (1-p) r1|).
We do NOT transcribe the closed form into the optimiser: the minimum is estimated by (a) random POVMs
(b) the projector onto the positive part of X = p rho0 - (1-p) rho1 (the Helstrom measurement, which is
optimal by the standard argument), and the smaller of the two is compared with the closed form.
Exit 0 = PASS."""
import numpy as np

SIG = [np.array([[0, 1], [1, 0]], complex), np.array([[0, -1j], [1j, 0]]), np.array([[1, 0], [0, -1]], complex)]


def rho(r):
    return 0.5 * (np.eye(2) + sum(ri * s for ri, s in zip(r, SIG)))


def err(r0, r1, p, M0):
    M1 = np.eye(2) - M0
    return (p * np.trace(rho(r0) @ M1) + (1 - p) * np.trace(rho(r1) @ M0)).real


def is_effect(M0, tol=1e-9):
    w = np.linalg.eigvalsh((M0 + M0.conj().T) / 2)
    return w.min() >= -tol and w.max() <= 1 + tol


def min_err_from_definition(r0, r1, p, rng, n_random=200):
    X = p * rho(r0) - (1 - p) * rho(r1)
    w, V = np.linalg.eigh(X)
    P = (V[:, w > 0]) @ (V[:, w > 0]).conj().T if (w > 0).any() else np.zeros((2, 2), complex)
    cands = [np.zeros((2, 2), complex), np.eye(2), P]
    for _ in range(n_random):
        A = rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2))
        H = A @ A.conj().T
        cands.append(H / max(np.linalg.eigvalsh(H).max(), 1e-12) * rng.uniform(0, 1))
    assert all(is_effect(c) for c in cands)
    return min(err(r0, r1, p, c) for c in cands)


def closed_form(r0, r1, p):
    v = p * np.asarray(r0) - (1 - p) * np.asarray(r1)
    return 0.5 - 0.5 * max(abs(2 * p - 1), np.linalg.norm(v))


def main():
    rng = np.random.default_rng(20260906)
    worst = 0.0
    for _ in range(600):
        r0 = rng.normal(size=3); r0 *= rng.uniform(0, 1) / np.linalg.norm(r0)
        r1 = rng.normal(size=3); r1 *= rng.uniform(0, 1) / np.linalg.norm(r1)
        p = rng.uniform(0.02, 0.98)
        worst = max(worst, abs(min_err_from_definition(r0, r1, p, rng) - closed_form(r0, r1, p)))
    ok = worst < 1e-9
    print(("PASS" if ok else "FAIL") + f": max |min Err − closed form| = {worst:.2e} over 600 instances")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
