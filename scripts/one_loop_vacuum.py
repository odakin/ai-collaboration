#!/usr/bin/env python3
"""Exact radial log integrals, one-loop MSbar vacuum terms and logarithmic stationary points; --selftest.

These are formula evaluators, not a choice of quantum measure or regulator.
Masses and cutoffs are supplied as squared quantities. The cutoff function
subtracts the massless reference determinant; any other counterterm is the
caller's responsibility. MSbar uses the scalar/fermion finite constant 3/2;
it is not a vector-field effective-potential prescription.
"""
from __future__ import annotations

import argparse
import mpmath as mp
import sympy as s


def _nonnegative(value, name):
    value = s.sympify(value)
    if value.is_negative:
        raise ValueError(f'{name} must be nonnegative')
    return value


def _positive(value, name):
    value = s.sympify(value)
    if value.is_nonpositive:
        raise ValueError(f'{name} must be positive')
    return value


def radial_log_integral(mass_sq, cutoff_sq, reference_sq=1):
    """Integral from 0 to cutoff_sq of t*log((t+mass_sq)/reference_sq) dt."""
    a = _nonnegative(mass_sq, 'mass_sq')
    L = _nonnegative(cutoff_sq, 'cutoff_sq')
    r = _positive(reference_sq, 'reference_sq')
    if L.is_zero:
        return s.S.Zero
    if a.is_zero:
        return L**2*s.log(L/r)/2 - L**2/4
    return ((L**2-a**2)*s.log((L+a)/r)/2 - L**2/4
            + a*L/2 + a**2*s.log(a/r)/2)


def cutoff_vacuum_shift(mass_sq, cutoff_sq, *, degrees=4, fermionic=True):
    """Four-dimensional determinant relative to zero mass, per coordinate volume.

One real scalar has degrees=1, fermionic=False. One Dirac field has degrees=4,
fermionic=True. No field-dependent volume factor is inserted here.
"""
    n = _positive(degrees, 'degrees')
    difference = radial_log_integral(mass_sq, cutoff_sq) - radial_log_integral(0, cutoff_sq)
    return (-1 if fermionic else 1)*n*difference/(32*s.pi**2)


def msbar_vacuum(mass_sq, scale_sq, *, degrees=4, fermionic=True):
    """Renormalized one-loop scalar/fermion vacuum energy; finite constant 3/2."""
    a = _nonnegative(mass_sq, 'mass_sq')
    mu = _positive(scale_sq, 'scale_sq')
    n = _positive(degrees, 'degrees')
    if a.is_zero:
        return s.S.Zero
    return (-1 if fermionic else 1)*n*a**2*(s.log(a/mu)-s.Rational(3, 2))/(64*s.pi**2)


def logarithmic_stationary_point(constant, log_coefficient, *, scale=1, power=4, log_power=2):
    """Positive stationary point and curvature of x^p [A+B log(k*x^r)].

Requires real A,B, nonzero B, and positive k,p,r. Curvature is with respect
to x; its sign is not a statement about constrained dynamics or kinetic terms.
"""
    A, B = s.sympify(constant), s.sympify(log_coefficient)
    if B.is_zero:
        raise ValueError('log_coefficient must be nonzero')
    k, p, r = (_positive(value, name) for value, name in
               [(scale, 'scale'), (power, 'power'), (log_power, 'log_power')])
    point = k**(-1/r)*s.exp(-A/(B*r)-1/p)
    return point, p*B*r*point**(p-2)


def selftest():
    a,L,mu,t=s.symbols('a L mu t',positive=True)
    J=radial_log_integral(a,L,mu)
    assert s.simplify(s.diff(J,L)-L*s.log((L+a)/mu)) == 0
    assert s.limit(J,L,0,dir='+') == 0
    assert s.simplify(s.limit(J,a,0,dir='+')-radial_log_integral(0,L,mu)) == 0
    with mp.workdps(55):
        evaluate=s.lambdify((a,L,mu),J,'mpmath')
        for av,lv,rv in [(mp.mpf('0.037'),mp.mpf('2.7'),mp.mpf('1.3')),
                         (mp.mpf('4.2'),mp.mpf('0.8'),mp.mpf('3.1'))]:
            direct=mp.quad(lambda x:x*mp.log((x+av)/rv),[0,lv])
            assert abs(direct-evaluate(av,lv,rv)) < mp.mpf('1e-45')
        # UV-convergent third mass derivative fixes sign and multiplicity.
        av=mp.mpf('2.3')
        direct=-4/(16*mp.pi**2)*mp.quad(lambda x:x/(x+av)**3,[0,av,mp.inf])
        assert abs(direct+1/(8*mp.pi**2*av)) < mp.mpf('1e-45')
    dirac=msbar_vacuum(a,mu)
    scalar=msbar_vacuum(a,mu,degrees=1,fermionic=False)
    assert s.simplify(dirac+4*scalar) == 0
    assert s.simplify(s.diff(dirac,a,3)+1/(8*s.pi**2*a)) == 0
    epsilon=s.symbols('epsilon')
    pole_series=s.series(s.gamma(epsilon)/((epsilon-1)*(epsilon-2)),epsilon,0,1).removeO()
    bare=2*a**2/(4*s.pi)**2*pole_series*(1+epsilon*s.log(4*s.pi*mu/a))
    pole=a**2/(16*s.pi**2)*(1/epsilon-s.EulerGamma+s.log(4*s.pi))
    assert s.simplify(s.expand_log(s.limit(bare-pole,epsilon,0)-dirac,force=True)) == 0
    A,B=s.symbols('A B',real=True,nonzero=True)
    k,x=s.symbols('k x',positive=True)
    point,curvature=logarithmic_stationary_point(A,B,scale=k,power=6,log_power=3)
    V=x**6*(A+B*s.log(k*x**3))
    assert s.simplify(s.expand_log(s.diff(V,x).subs(x,point),force=True)) == 0
    assert s.simplify(s.expand_log(s.diff(V,x,2).subs(x,point)-curvature,force=True)) == 0
    # Mutated candidates must fail against independent identities.
    for wrong in [-dirac,dirac/2]:
        assert s.simplify(s.diff(wrong,a,3)+1/(8*s.pi**2*a)) != 0
    bad_point=k**(-s.Rational(1,3))*s.exp(-A/(3*B))
    assert s.simplify(s.expand_log(s.diff(V,x).subs(x,bad_point),force=True)) != 0
    assert cutoff_vacuum_shift(0,L) == 0
    assert radial_log_integral(0.0,1)==-s.Rational(1,4)
    assert radial_log_integral(2,0.0)==0
    assert msbar_vacuum(0.0,2)==0
    assert cutoff_vacuum_shift(0.0,1)==0
    assert cutoff_vacuum_shift(1,0.0)==0
    for args in [(-1,2),(1,-2)]:
        try:
            radial_log_integral(*args)
        except ValueError:
            pass
        else:
            raise AssertionError('negative-domain foil was accepted')
    print('PASS: quadrature, endpoints, dimensional subtraction, mass derivative, extrema and foils')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selftest',action='store_true',required=True)
    parser.parse_args()
    selftest()
