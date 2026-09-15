#!/usr/bin/env python3
"""Exact density-frame tensor algebra, auxiliary-image constraints, and free-field projectors; --selftest.

This module keeps reusable algebra for a contravariant frame density of
weight one half.  It separates four questions that are easy to conflate:

* matrix and connection identities on an invertible frame;
* the kernel, image, and restricted inverse of the first-derivative gravity
  quadratic form;
* the finite ambient polynomial obtained after an auxiliary-field shift;
* the moving image constraint that still has to be imposed on that polynomial.

The metric signature is (+,-,...,-), kappa is set to one, and every local
three-index tensor is stored with all indices lowered.  Odd-dimensional tests
use sqrt(abs(det g)); with mostly-minus signature, sqrt(-det g) is real on a
real oriented frame only in even dimension.

The selftest uses exact SymPy arithmetic.  It includes a deliberately stronger
unrestricted-auxiliary reading and a frozen-background image constraint as
negative controls, plus an independent Fierz-Pauli construction of the free
density-frame propagator.  It does not define a functional measure or a BRST
law for an independent nonlinear auxiliary field.
"""
from __future__ import annotations

import argparse
from itertools import permutations, product

import sympy as sp


def indices(d):
    return list(product(range(d), repeat=3))


def signature(d):
    return [1] + [-1] * (d - 1)


def metric(d, i, j):
    return signature(d)[i] if i == j else 0


def zero(d):
    return {key: sp.S.Zero for key in indices(d)}


def tensor(d, seed=0):
    return {
        (i, j, k): sp.Integer(((19 * i + 7 * j + 3 * k + i * j + seed * (k + 1)) % 11) - 5)
        for i, j, k in indices(d)
    }


def add(x, y, scale=1):
    return {key: sp.expand(x[key] + scale * y[key]) for key in x}


def pairing(x, y, d):
    signs = signature(d)
    return sp.expand(
        sum(signs[i] * signs[j] * signs[k] * x[i, j, k] * y[i, j, k] for i, j, k in x)
    )


def op(x, d, trace_mutant=False):
    """First-derivative gravity quadratic map in all-lower local indices."""
    signs = signature(d)
    trace_ik = [sum(signs[c] * x[i, c, c] for c in range(d)) for i in range(d)]
    trace_ii = [sum(signs[c] * x[c, c, i] for c in range(d)) for i in range(d)]
    coefficient = sp.Rational(2, d - 2) + int(trace_mutant)
    return {
        (i, j, k): sp.expand(
            2
            * (
                -x[j, k, i]
                + x[i, k, j]
                - x[k, j, i]
                - x[k, i, j]
                + x[i, j, k]
                + x[j, i, k]
                - 2 * metric(d, i, j) * trace_ii[k]
                - coefficient * metric(d, j, k) * trace_ik[i]
            )
        )
        for i, j, k in indices(d)
    }


def projector(x, d, mutant=False):
    """Oblique projector onto the kernel of op()."""
    signs = signature(d)
    trace_ii = [sum(signs[c] * x[c, c, i] for c in range(d)) for i in range(d)]
    return {
        (i, j, k): sp.expand(
            sp.Rational(1, 2)
            * (x[i, j, k] + x[j, i, k] + x[j, k, i] + x[k, j, i] - x[i, k, j] - x[k, i, j])
            + metric(d, i, k) * trace_ii[j]
            - (1 - int(mutant)) * metric(d, j, k) * trace_ii[i]
        )
        for i, j, k in indices(d)
    }


def inverse(a, d, mutant=False):
    """Restricted inverse from Im(op) to the first-pair antisymmetric complement."""
    signs = signature(d)
    trace = [sum(signs[c] * a[i, c, c] for c in range(d)) for i in range(d)]
    coefficient = sp.Rational(1, 8) if not mutant else sp.Rational(1, 4)
    return {
        (i, j, k): sp.expand(a[i, k, j] / 4 - coefficient * metric(d, j, k) * trace[i])
        for i, j, k in indices(d)
    }


def density_connection(x, d, mutant=False):
    """Torsion-free density connection built from a density-frame first jet."""
    signs = signature(d)
    trace = [sum(signs[c] * x[i, c, c] for c in range(d)) for i in range(d)]

    def anholonomy(a, b, k):
        return x[a, k, b] - x[b, k, a]

    coefficient = sp.Rational(1, d - 2) + int(mutant)
    return {
        (m, a, b): sp.expand(
            (
                anholonomy(a, b, m)
                + anholonomy(m, b, a)
                - anholonomy(m, a, b)
            )
            / 2
            + coefficient
            * (
                trace[m] * metric(d, a, b)
                + trace[b] * metric(d, m, a)
                - trace[a] * metric(d, m, b)
            )
        )
        for m, a, b in indices(d)
    }


def auxiliary_from_connection(connection, d):
    """Auxiliary image element obtained from the antisymmetric density connection."""
    signs = signature(d)
    vector = [
        sum(signs[c] * (connection[c, k, c] - connection[c, c, k]) for c in range(d))
        for k in range(d)
    ]
    return {
        (i, j, k): sp.expand(
            2 * (metric(d, i, j) * vector[k] + connection[j, i, k] - connection[j, k, i])
        )
        for i, j, k in indices(d)
    }


def exact_frame(d, seed=0):
    """Dense rational frame with positive determinant."""
    upper = sp.eye(d)
    lower = sp.eye(d)
    for i in range(d):
        for j in range(i + 1, d):
            upper[i, j] = sp.Rational(((i + 2 * j + seed) % 3) - 1, 3)
            lower[j, i] = sp.Rational(((2 * i + j + seed) % 3) - 1, 4)
    return upper * lower


def first_jets(d, seed=0):
    return [
        sp.Matrix(
            d,
            d,
            lambda a, b: sp.Rational(((5 * m + 3 * a + 7 * b + seed) % 13) - 6, 5),
        )
        for m in range(d)
    ]


def geometry(frame_density, first_jet):
    """Derive metric, Christoffels, and spin connections from an independent route."""
    d = frame_density.rows
    eta = sp.diag(*signature(d))
    inverse_frame_density = frame_density.inv()
    volume = frame_density.det() ** sp.Rational(2, d - 2)
    root = sp.sqrt(volume)
    coframe = root * inverse_frame_density.T
    frame = frame_density / root
    trace = [(inverse_frame_density * first_jet[m]).trace() for m in range(d)]
    shift = [value / sp.Integer(d - 2) for value in trace]
    derivative_inverse = [
        -inverse_frame_density * first_jet[m] * inverse_frame_density for m in range(d)
    ]
    derivative_volume = [2 * volume * value for value in shift]
    derivative_coframe = [
        root * (shift[m] * inverse_frame_density.T + derivative_inverse[m].T) for m in range(d)
    ]
    spacetime_metric = volume * inverse_frame_density.T * eta * inverse_frame_density
    inverse_metric = spacetime_metric.inv()
    derivative_metric = [
        derivative_volume[m] * inverse_frame_density.T * eta * inverse_frame_density
        + volume
        * (
            derivative_inverse[m].T * eta * inverse_frame_density
            + inverse_frame_density.T * eta * derivative_inverse[m]
        )
        for m in range(d)
    ]
    christoffel = [
        sp.Matrix(
            d,
            d,
            lambda r, n: sum(
                inverse_metric[r, q]
                * (
                    derivative_metric[m][n, q]
                    + derivative_metric[n][m, q]
                    - derivative_metric[q][m, n]
                )
                / 2
                for q in range(d)
            ),
        )
        for m in range(d)
    ]
    spin_connection = [
        coframe.T * christoffel[m] * frame - derivative_coframe[m].T * frame for m in range(d)
    ]
    density_spin_connection = [
        spin_connection[m] + shift[m] * sp.eye(d) for m in range(d)
    ]
    x = {
        (i, j, k): sum(
            signature(d)[j]
            * inverse_frame_density[j, a]
            * frame_density[m, i]
            * first_jet[m][a, k]
            for a in range(d)
            for m in range(d)
        )
        for i, j, k in indices(d)
    }
    local_connection = {
        (i, a, b): sum(
            frame_density[m, i]
            * signature(d)[a]
            * density_spin_connection[m][a, b]
            for m in range(d)
        )
        for i, a, b in indices(d)
    }
    return {
        "d": d,
        "E": frame_density,
        "H": first_jet,
        "F": inverse_frame_density,
        "e": volume,
        "g": spacetime_metric,
        "gi": inverse_metric,
        "coframe": coframe,
        "frame": frame,
        "trace": trace,
        "shift": shift,
        "dt": derivative_coframe,
        "dg": derivative_metric,
        "Gamma": christoffel,
        "omega": spin_connection,
        "Omega": density_spin_connection,
        "x": x,
        "w": local_connection,
    }


def spin_bulk(geometry_data, mutant=False):
    """Bulk term after integrating the density-frame curvature action by parts."""
    d = geometry_data["d"]
    frame_density = geometry_data["E"]
    first_jet = geometry_data["H"]
    connection = geometry_data["Omega"]
    signs = signature(d)
    derivative = sp.S.Zero
    commutator = sp.S.Zero
    comm = {
        (mu, nu): connection[mu] * connection[nu] - connection[nu] * connection[mu]
        for mu in range(d)
        for nu in range(d)
    }
    for mu, nu, a, b in product(range(d), repeat=4):
        derivative += 2 * signs[b] * (
            first_jet[mu][mu, a] * frame_density[nu, b]
            + frame_density[mu, a] * first_jet[mu][nu, b]
            - first_jet[mu][nu, a] * frame_density[mu, b]
            - frame_density[nu, a] * first_jet[mu][mu, b]
        ) * connection[nu][a, b]
        commutator += (
            -2 * signs[b] * frame_density[mu, a] * frame_density[nu, b] * comm[mu, nu][a, b]
        )
    return sp.expand(derivative + (-1 if mutant else 1) * commutator)


def constant_matrix_map(function, d):
    keys = indices(d)
    columns = []
    for key in keys:
        basis = zero(d)
        basis[key] = sp.S.One
        result = function(basis, d)
        columns.append(sp.Matrix([result[item] for item in keys]))
    return sp.Matrix.hstack(*columns)


def world_auxiliary(local_auxiliary, frame_density):
    d = frame_density.rows
    inverse_frame_density = frame_density.inv()
    signs = signature(d)
    return {
        (i, alpha, k): sum(
            signs[i] * signs[k] * local_auxiliary[i, j, k] * inverse_frame_density[j, alpha]
            for j in range(d)
        )
        for i, alpha, k in indices(d)
    }


def world_inverse_quadratic(auxiliary, frame_density, mutant=False):
    d = frame_density.rows
    signs = signature(d)
    coefficient = sp.Rational(1, 8) if not mutant else sp.Rational(1, 4)
    return sp.expand(
        sum(
            signs[i]
            * auxiliary[i, alpha, a]
            * auxiliary[i, beta, b]
            * (
                frame_density[alpha, b] * frame_density[beta, a] / 4
                - coefficient * frame_density[alpha, a] * frame_density[beta, b]
            )
            for i, alpha, a, beta, b in product(range(d), repeat=5)
        )
    )


def density_metric_map(theta, d):
    """Linear map from a mixed density-frame perturbation to h with lower indices."""
    eta = sp.diag(*signature(d))
    return -eta * theta - theta.T * eta + 2 * sp.trace(theta) * eta / (d - 2)


def free_density_hessian(d, covector, rho=sp.Rational(2, 3)):
    """Build the free theta Hessian from Fierz-Pauli plus the two linear gauges."""
    eta = sp.diag(*signature(d))
    variables = sp.symbols("theta:" + str(d * d))
    theta = sp.Matrix(d, d, variables)
    h = density_metric_map(theta, d)
    trace_h = sp.trace(eta * h)
    divergence = h * eta * covector
    momentum_squared = (covector.T * eta * covector)[0]
    fierz_pauli = (
        momentum_squared * sp.trace(eta * h * eta * h) / 2
        - (divergence.T * eta * divergence)[0]
        + (divergence.T * eta * covector)[0] * trace_h
        - momentum_squared * trace_h * trace_h / 2
    )
    diffeomorphism_gauge = (theta * eta + (theta * eta).T) * covector
    lorentz_gauge = eta * theta - (eta * theta).T
    lagrangian = (
        fierz_pauli
        + (diffeomorphism_gauge.T * eta * diffeomorphism_gauge)[0]
        + sp.trace(lorentz_gauge.T * eta * lorentz_gauge * eta) / (2 * rho)
    )
    return sp.hessian(lagrangian, variables), variables, theta, h


def free_density_propagator(d, covector, rho=sp.Rational(2, 3), contact=True):
    """Candidate inverse of free_density_hessian(), omitting the overall i."""
    eta = sp.diag(*signature(d))
    momentum_squared = (covector.T * eta * covector)[0]
    result = sp.zeros(d * d)
    for a, b, c, e in product(range(d), repeat=4):
        base = eta[a, c] * eta[b, e]
        swap = int(a == e) * int(c == b)
        trace = int(a == b) * int(c == e)
        result[a * d + b, c * d + e] = (base + swap - trace) / (8 * momentum_squared)
        if contact:
            result[a * d + b, c * d + e] += rho * (base - swap) / 8
    return result


def reject_mutant(function, label):
    """A foil succeeds only when the intended assertion rejects the mutant."""
    try:
        function()
    except AssertionError as error:
        print("FOIL-TEETH:", label, error)
        return
    raise AssertionError("FOIL-BROKEN: " + label)


# Backward-compatible short name used by campaign-local foil wrappers.
reject = reject_mutant


def selftest():
    # Kernel, oblique complement, and restricted inverse on the entire d=3 space.
    d = 3
    operator = sp.SparseMatrix(constant_matrix_map(op, d))
    kernel_projector = sp.SparseMatrix(constant_matrix_map(projector, d))
    restricted_inverse = sp.SparseMatrix(constant_matrix_map(inverse, d))
    identity = sp.eye(d**3)
    signs = signature(d)
    metric_tensor = sp.diag(*[signs[i] * signs[j] * signs[k] for i, j, k in indices(d)])
    assert kernel_projector * kernel_projector == kernel_projector
    assert operator * kernel_projector == sp.zeros(d**3)
    assert restricted_inverse * operator == identity - kernel_projector
    assert operator * restricted_inverse * operator == operator
    assert operator * restricted_inverse == identity - metric_tensor * kernel_projector.T * metric_tensor
    assert sp.trace(kernel_projector) == d * d * (d + 1) // 2
    assert sp.trace(identity - kernel_projector) == d * d * (d - 1) // 2

    # Independent metric/Christoffel route on a dense frame.
    data = geometry(exact_frame(4, 1), first_jets(4, 2))
    assert density_connection(data["x"], 4) == data["w"]
    assert auxiliary_from_connection(data["w"], 4) == op(data["x"], 4)
    assert spin_bulk(data) == pairing(data["x"], op(data["x"], 4), 4) / 2

    # Constrained elimination and its unrestricted negative control.
    local_auxiliary = op(data["x"], 4)
    world = world_auxiliary(local_auxiliary, data["E"])
    assert world_inverse_quadratic(world, data["E"]) == pairing(local_auxiliary, inverse(local_auxiliary, 4), 4)
    symmetric = zero(4)
    for permutation in permutations((0, 1, 2)):
        symmetric[permutation] = sp.S.One
    assert op(symmetric, 4) == zero(4)
    unrestricted = {key: 4 * value for key, value in symmetric.items()}
    assert pairing(symmetric, unrestricted, 4) / 2 == 12
    assert pairing(symmetric, op(symmetric, 4), 4) / 2 == 0

    # A field-dependent image cannot be replaced by its flat value.
    parameter = sp.symbols("t")
    source = zero(4)
    source[0, 1, 2] = sp.S.One
    flat_auxiliary = op(source, 4)
    shear = sp.eye(4)
    shear[0, 1] = parameter
    transported = {
        (i, j, k): sum(shear[alpha, j] * flat_auxiliary[i, alpha, k] for alpha in range(4))
        for i, j, k in indices(4)
    }
    residual = add(op(inverse(transported, 4), 4), transported, -1)
    assert residual[0, 0, 2] == 2 * parameter
    def require_frozen_image():
        assert residual == zero(4), "field-dependent image residual"

    reject_mutant(require_frozen_image, "frozen image")

    # Independent Fierz-Pauli free-field inversion and metric projection.
    for dimension in (3, 4):
        covector = sp.Matrix([dimension + 2] + list(range(1, dimension)))
        hessian, variables, _theta, h = free_density_hessian(dimension, covector)
        propagator = free_density_propagator(dimension, covector)
        assert hessian * propagator == sp.eye(dimension * dimension)
        raised_h = sp.diag(*signature(dimension)) * h * sp.diag(*signature(dimension))
        metric_map = sp.Matrix(list(raised_h)).jacobian(variables)
        transformed = metric_map * propagator * metric_map.T
        assert transformed == metric_map * free_density_propagator(
            dimension, covector, contact=False
        ) * metric_map.T
        reject_mutant(
            lambda dimension=dimension, covector=covector, hessian=hessian: (
                hessian * free_density_propagator(dimension, covector, contact=False)
                == sp.eye(dimension * dimension)
            )
            or (_ for _ in ()).throw(AssertionError("missing antisymmetric contact term")),
            "contact term",
        )

    # Signature parity and the real volume-density convention.
    for dimension in (3, 4, 5, 6):
        coframe = exact_frame(dimension, 3)
        determinant = (coframe * sp.diag(*signature(dimension)) * coframe.T).det()
        assert determinant == (-1) ** (dimension - 1) * coframe.det() ** 2
        assert sp.sqrt(abs(determinant)) == coframe.det()
        assert (-determinant == coframe.det() ** 2) == (dimension % 2 == 0)

    print("selftest OK: density identities, moving image, restricted auxiliary, and free projectors")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", required=True)
    args = parser.parse_args()
    if args.selftest:
        selftest()


if __name__ == "__main__":
    main()
