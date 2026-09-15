#!/usr/bin/env python3
"""Definition-level audits for covariant action equivalence and polynomiality on exact backgrounds; --selftest.

The reusable core is an arbitrary-lapse FLRW geometry derived directly from
Christoffel symbols, a higher-derivative one-dimensional Euler operator, and a
four-function scalar-tensor action evaluator.  The selftest demonstrates how to
use them without promoting a restricted-background match into a general proof:

* a covariant identity supplies sufficiency, while arbitrary-lapse monomial
  coefficients supply a necessary analytic null-kernel test;
* constant and linear coefficient limits distinguish topological terms from
  genuine field-dependent couplings;
* an anisotropic frame slice exposes inverse-determinant dependence that a
  conformal slice cannot see;
* a principal-symbol coefficient distinguishes a kinetic obstruction from
  derivative-free terms.

The scalar-tensor conventions are signature (+---), X=(grad phi)^2/2, and the
action basis used by Kobayashi, Yamaguchi, and Yokoyama after the corresponding
signature translation.  Their published scalar-Gauss-Bonnet representative is
included with its logarithmic G5 coefficient.  No claim about a particular
later paper, field redefinition, quantum measure, or unrestricted auxiliary
construction is made here.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
from itertools import permutations, product

import sympy as s


def gamma_matrices():
    zero = s.zeros(2)
    pauli = [
        s.Matrix([[0, 1], [1, 0]]),
        s.Matrix([[0, -s.I], [s.I, 0]]),
        s.diag(1, -1),
    ]
    return [s.diag(1, 1, -1, -1)] + [
        zero.row_join(matrix).col_join((-matrix).row_join(zero)) for matrix in pauli
    ]


def gamma3(gamma, a, b, c):
    """Unit-weight antisymmetrized product gamma^[a gamma^b gamma^c]."""
    result = s.zeros(4)
    for permutation in permutations(range(3)):
        sign = (-1) ** sum(
            permutation[i] > permutation[j]
            for i in range(3)
            for j in range(i + 1, 3)
        )
        indices = [a, b, c]
        result += (
            sign
            * gamma[indices[permutation[0]]]
            * gamma[indices[permutation[1]]]
            * gamma[indices[permutation[2]]]
            / 6
        )
    return result


def el1(lagrangian, field, coordinate, max_order=2):
    """One-dimensional Euler operator, without imposing equations of motion."""
    result = s.diff(lagrangian, field)
    for order in range(1, max_order + 1):
        result += (-1) ** order * s.diff(
            s.diff(lagrangian, s.diff(field, coordinate, order)), coordinate, order
        )
    return s.simplify(result.doit())


@lru_cache(None)
def flrw():
    """Derive exact FLRW curvature and scalar Hessians before fixing the lapse."""
    time = s.symbols("t", real=True)
    scale_factor, lapse, scalar = [s.Function(name)(time) for name in ("a", "N", "p")]
    metric = [lapse**2, -scale_factor**2, -scale_factor**2, -scale_factor**2]
    inverse_metric = [1 / component for component in metric]

    def derivative(expression, coordinate):
        return s.diff(expression, time) if coordinate == 0 else s.S.Zero

    connection = {}
    for upper, first, second in product(range(4), repeat=3):
        value = inverse_metric[upper] / 2 * (
            (derivative(metric[upper], first) if upper == second else 0)
            + (derivative(metric[upper], second) if upper == first else 0)
            - (derivative(metric[first], upper) if first == second else 0)
        )
        connection[upper, first, second] = s.simplify(value)

    curvature = {}
    for upper, lower, first, second in product(range(4), repeat=4):
        curvature[upper, lower, first, second] = s.simplify(
            derivative(connection[upper, second, lower], first)
            - derivative(connection[upper, first, lower], second)
            + sum(
                connection[upper, first, middle] * connection[middle, second, lower]
                - connection[upper, second, middle] * connection[middle, first, lower]
                for middle in range(4)
            )
        )

    ricci = s.Matrix(
        4,
        4,
        lambda lower, second: s.simplify(
            sum(curvature[upper, lower, upper, second] for upper in range(4))
        ),
    )
    ricci_scalar = s.simplify(sum(inverse_metric[i] * ricci[i, i] for i in range(4)))
    ricci_squared = s.simplify(
        sum(
            inverse_metric[i] * inverse_metric[j] * ricci[i, j] ** 2
            for i, j in product(range(4), repeat=2)
        )
    )
    riemann_squared = s.simplify(
        sum(
            metric[upper]
            * inverse_metric[lower]
            * inverse_metric[first]
            * inverse_metric[second]
            * value**2
            for (upper, lower, first, second), value in curvature.items()
        )
    )
    gauss_bonnet = s.factor(riemann_squared - 4 * ricci_squared + ricci_scalar**2)

    hessian = s.Matrix(
        4,
        4,
        lambda first, second: (
            s.diff(scalar, time, 2) if first == second == 0 else 0
        )
        - connection[0, first, second] * s.diff(scalar, time),
    )
    mixed_hessian = s.diag(*inverse_metric) * hessian
    box = s.simplify(s.trace(mixed_hessian))
    hessian_squared = s.simplify(s.trace(mixed_hessian * mixed_hessian))
    hessian_cubed = s.simplify(s.trace(mixed_hessian * mixed_hessian * mixed_hessian))
    einstein = ricci - s.diag(*metric) * ricci_scalar / 2
    einstein_hessian = s.simplify(
        sum(
            inverse_metric[i] * inverse_metric[j] * einstein[i, j] * hessian[i, j]
            for i, j in product(range(4), repeat=2)
        )
    )
    kinetic = s.diff(scalar, time) ** 2 / (2 * lapse**2)
    return {
        "t": time,
        "a": scale_factor,
        "n": lapse,
        "p": scalar,
        "metric": metric,
        "inverse": inverse_metric,
        "connection": connection,
        "ricci": ricci,
        "R": ricci_scalar,
        "GB": gauss_bonnet,
        "X": kinetic,
        "box": box,
        "Q": s.factor(box**2 - hessian_squared),
        "C": s.factor(box**3 - 3 * box * hessian_squared + 2 * hessian_cubed),
        "GH": einstein_hessian,
        "density": lapse * scale_factor**3,
    }


def horndeski_flrw(functions):
    """Substitute four Gi(P,X) callables into the independently derived geometry."""
    geometry = flrw()
    scalar_symbol, kinetic_symbol = s.symbols("P X")
    g2, g3, g4, g5 = [function(scalar_symbol, kinetic_symbol) for function in functions]
    substitution = {scalar_symbol: geometry["p"], kinetic_symbol: geometry["X"]}
    scalar_lagrangian = (
        g2.subs(substitution)
        + g3.subs(substitution) * geometry["box"]
        + g4.subs(substitution) * geometry["R"]
        - s.diff(g4, kinetic_symbol).subs(substitution) * geometry["Q"]
        + g5.subs(substitution) * geometry["GH"]
        + s.diff(g5, kinetic_symbol).subs(substitution) * geometry["C"] / 6
    )
    return s.factor(geometry["density"] * scalar_lagrangian)


def horndeski_surface_functions(g3_factor=3):
    """General local divergence tuple parameterized by A(phi) and f(phi)."""
    return [
        lambda phi, kinetic: 2 * s.diff(s.Function("A")(phi), phi) * kinetic
        + 2 * s.diff(s.Function("f")(phi), phi, 3) * kinetic**2,
        lambda phi, kinetic: s.Function("A")(phi)
        + g3_factor * s.diff(s.Function("f")(phi), phi, 2) * kinetic,
        lambda phi, kinetic: -s.diff(s.Function("f")(phi), phi) * kinetic,
        lambda phi, kinetic: s.Function("f")(phi),
    ]


def scalar_gauss_bonnet_functions(reference_scale=1):
    """Published scalar-Gauss-Bonnet Horndeski representative in (+---) conventions."""
    return [
        lambda chi, kinetic: 8
        * s.diff(s.Function("chi")(chi), chi, 4)
        * kinetic**2
        * (3 - s.log(kinetic / reference_scale)),
        lambda chi, kinetic: 4
        * s.diff(s.Function("chi")(chi), chi, 3)
        * kinetic
        * (7 - 3 * s.log(kinetic / reference_scale)),
        lambda chi, kinetic: -4
        * s.diff(s.Function("chi")(chi), chi, 2)
        * kinetic
        * (2 - s.log(kinetic / reference_scale)),
        lambda chi, kinetic: -4
        * s.diff(s.Function("chi")(chi), chi)
        * s.log(kinetic / reference_scale),
    ]


def lapse_monomial_coefficients(power, coefficient, coefficient_derivative, hubble, kinetic):
    """Necessary FLRW lapse equations for Gi=c(phi) X^power, divided by a^3."""
    return [
        (1 - 2 * power) * coefficient * kinetic**power,
        2 * kinetic ** (power + 1) * (coefficient_derivative - 6 * power * coefficient * hubble),
        12
        * kinetic ** (power + 1)
        * (2 * power + 1)
        * hubble
        * ((2 * power - 1) * coefficient * hubble - coefficient_derivative),
        4
        * kinetic ** (power + 2)
        * (2 * power + 3)
        * hubble**2
        * (3 * coefficient_derivative - 2 * power * coefficient * hubble),
    ]


def reject_mutant(check, **kwargs):
    """A foil passes only on the intended assertion failure."""
    try:
        check(**kwargs)
    except AssertionError as error:
        print("FOIL-TEETH:", error)
        return
    raise AssertionError("FOIL-BROKEN: mutant was accepted")


def _check_surface_tuple(g3_factor=3):
    geometry = flrw()
    lagrangian = horndeski_flrw(horndeski_surface_functions(g3_factor))
    for field, name in (
        (geometry["n"], "lapse"),
        (geometry["a"], "scale factor"),
        (geometry["p"], "scalar"),
    ):
        assert el1(lagrangian, field, geometry["t"]) == 0, "surface tuple " + name


def selftest():
    geometry = flrw()
    time, scale_factor, lapse, scalar = [
        geometry[key] for key in ("t", "a", "n", "p")
    ]

    # Clifford conventions and the axial three-gamma reduction.
    gamma = gamma_matrices()
    eta = [1, -1, -1, -1]
    for a, b in product(range(4), repeat=2):
        assert gamma[a] * gamma[b] + gamma[b] * gamma[a] == 2 * (
            eta[a] if a == b else 0
        ) * s.eye(4)
    for m, a, b in product(range(4), repeat=3):
        assert gamma[m] * gamma[a] * gamma[b] + gamma[a] * gamma[b] * gamma[m] == (
            2 * gamma3(gamma, m, a, b) + 2 * (eta[a] if a == b else 0) * gamma[m]
        )

    # Covariant sufficiency of the analytic null tuple and a coefficient foil.
    _check_surface_tuple()
    reject_mutant(_check_surface_tuple, g3_factor=2)

    # Necessary lapse coefficients for every analytic monomial.
    power = s.symbols("n", integer=True, nonnegative=True)
    coefficient = s.Function("c")(time)
    derivative = s.diff(coefficient, time)
    hubble = s.diff(scale_factor, time) / scale_factor
    kinetic = 1 / (2 * lapse**2)
    expected = lapse_monomial_coefficients(power, coefficient, derivative, hubble, kinetic)
    for sector in range(4):
        functions = [lambda phi, x: s.S.Zero for _ in range(4)]
        functions[sector] = lambda phi, x: s.Function("c")(phi) * x**power
        lagrangian = horndeski_flrw(functions).subs(scalar, time).doit()
        actual = el1(lagrangian, lapse, time)
        actual = s.simplify(
            actual.subs({s.diff(lapse, time): 0, s.diff(lapse, time, 2): 0})
            / scale_factor**3
        )
        assert s.simplify(actual - expected[sector]) == 0

    # Linear scalar-Gauss-Bonnet coupling: arbitrary-lapse action equivalence.
    direct = geometry["density"] * scalar * geometry["GB"]
    linear_functions = [lambda phi, x: s.S.Zero] * 3 + [
        lambda phi, x: -4 * s.log(x)
    ]
    represented = horndeski_flrw(linear_functions)
    for field in (scale_factor, lapse, scalar):
        assert el1(direct - represented, field, time) == 0
    assert el1(geometry["density"] * geometry["GB"], scale_factor, time) == 0
    assert s.simplify(
        el1(direct, scalar, time) - geometry["density"] * geometry["GB"]
    ) == 0

    # The full published tuple gives the correct scalar source on exact de Sitter.
    hubble_constant = s.symbols("H", nonzero=True, real=True)
    phi, velocity, acceleration, jerk, fourth = s.symbols("phi v w z r", real=True)
    x_symbol, x0 = s.symbols("X X0", positive=True)
    chi = s.Function("chi")(phi)
    volume = s.exp(3 * hubble_constant * time)
    box = acceleration + 3 * hubble_constant * velocity
    hessian_squared = acceleration**2 + 3 * hubble_constant**2 * velocity**2
    cubic = 18 * hubble_constant**2 * velocity**2 * acceleration + 6 * hubble_constant**3 * velocity**3
    einstein_hessian = 3 * hubble_constant**2 * acceleration + 9 * hubble_constant**3 * velocity
    functions = scalar_gauss_bonnet_functions(x0)
    g2, g3, g4, g5 = [function(phi, x_symbol) for function in functions]
    lagrangian = volume * (
        g2
        + g3 * box
        - 12 * hubble_constant**2 * g4
        - s.diff(g4, x_symbol) * (box**2 - hessian_squared)
        + g5 * einstein_hessian
        + s.diff(g5, x_symbol) * cubic / 6
    ).subs(x_symbol, velocity**2 / 2)

    def total_derivative(expression):
        return (
            s.diff(expression, time)
            + velocity * s.diff(expression, phi)
            + acceleration * s.diff(expression, velocity)
            + jerk * s.diff(expression, acceleration)
            + fourth * s.diff(expression, jerk)
        )

    scalar_euler = s.simplify(
        (
            s.diff(lagrangian, phi)
            - total_derivative(s.diff(lagrangian, velocity))
            + total_derivative(total_derivative(s.diff(lagrangian, acceleration)))
        )
        / volume
    )
    assert s.simplify(scalar_euler - 24 * hubble_constant**4 * s.diff(chi, phi)) == 0

    # Matter polynomiality needs an anisotropic slice; conformal scaling is blind.
    parameter = s.symbols("u", positive=True)
    frame = s.diag(parameter, 1, 1, 1)
    densitized_metric = frame * s.diag(1, -1, -1, -1) * frame.T
    field_strength = s.zeros(4)
    field_strength[2, 3], field_strength[3, 2] = 1, -1
    maxwell = -sum(
        densitized_metric[i, r]
        * densitized_metric[j, q]
        * field_strength[i, j]
        * field_strength[r, q]
        for i, j, r, q in product(range(4), repeat=4)
    ) / (4 * frame.det())
    assert s.simplify(maxwell) == -1 / (2 * parameter)
    for order in range(13):
        assert s.diff(maxwell, parameter, order).subs(parameter, 1) != 0
    conformal = s.symbols("z", positive=True)
    assert (
        ((conformal * frame) * s.diag(1, -1, -1, -1) * (conformal * frame).T)[2, 2] ** 2
        / (conformal * frame).det()
        == densitized_metric[2, 2] ** 2 / frame.det()
    )
    assert s.sqrt(frame.det()) * frame[1, 1] == s.sqrt(parameter)

    print("selftest OK: covariant null tests, Gauss-Bonnet map, and matter polynomiality witnesses")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", required=True)
    args = parser.parse_args()
    if args.selftest:
        selftest()


if __name__ == "__main__":
    main()
