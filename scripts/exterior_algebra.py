#!/usr/bin/env python3
"""Exact coordinate differential forms and complementary inverse minors; --selftest.

A form is a dictionary mapping an index tuple to its coefficient in the wedge
basis. Thus {(0,1): f} means f dx0 wedge dx1, without a hidden factorial.
Normalized tensor antisymmetrization is an explicit option of densitized_inverse_minor.
"""
from __future__ import annotations

import argparse
from itertools import combinations
from math import factorial
import sympy as s


def permutation_sign(indices):
    if len(set(indices)) != len(indices):
        return 0
    return (-1)**sum(a>b for i,a in enumerate(indices) for b in indices[i+1:])


def clean(form):
    result={}
    for indices,value in form.items():
        if any(not isinstance(i,int) or i<0 for i in indices):
            raise ValueError('form indices must be nonnegative integers')
        sign=permutation_sign(indices)
        if sign:
            key=tuple(sorted(indices))
            result[key]=result.get(key,0)+sign*s.sympify(value)
    return {k:s.expand(v) for k,v in result.items() if s.expand(v)!=0}


def add(*forms):
    result={}
    for form in forms:
        for k,v in clean(form).items():
            result[k]=result.get(k,0)+v
    return clean(result)


def scale(coefficient, form):
    return clean({k:s.sympify(coefficient)*v for k,v in form.items()})


def wedge(first, second):
    result={}
    for I,u in clean(first).items():
        for J,v in clean(second).items():
            key=I+J
            result[key]=result.get(key,0)+u*v
    return clean(result)


def derivative(form, coordinates):
    result={}
    for indices,value in clean(form).items():
        if any(i>=len(coordinates) for i in indices):
            raise ValueError('form index exceeds coordinate dimension')
        for i,x in enumerate(coordinates):
            result=add(result,wedge({(i,):s.diff(value,x)},{indices:1}))
    return result


def densitized_inverse_minor(matrix, inverse_rows, inverse_columns, *, normalized=False):
    """Polynomial det(E)*det(E^-1[rows,cols]), also defined on singular E.

Rows/columns must be strictly increasing tuples of equal length. Jacobi's
complementary-minor formula avoids inversion. normalized=True divides by k!
for normalized antisymmetrization of the k inverse factors.
"""
    E=s.Matrix(matrix)
    if E.rows!=E.cols:
        raise ValueError('matrix must be square')
    rows,cols=tuple(inverse_rows),tuple(inverse_columns)
    if len(rows)!=len(cols):
        raise ValueError('minor dimensions must agree')
    for values in [rows,cols]:
        if (tuple(sorted(set(values)))!=values or
                any(not isinstance(i,int) or i<0 or i>=E.rows for i in values)):
            raise ValueError('indices must be strictly increasing and in range')
    other_rows=[i for i in range(E.rows) if i not in rows]
    other_cols=[i for i in range(E.rows) if i not in cols]
    value=(-1)**(sum(rows)+sum(cols))*E.extract(other_cols,other_rows).det()
    return value/s.Integer(factorial(len(rows))) if normalized else value


def selftest():
    x=s.symbols('x0:4')
    dx=[{(i,):s.S.One} for i in range(4)]
    alpha=add(scale(x[1]**2,dx[0]),scale(x[2]*x[3],dx[1]))
    beta=add(scale(x[0],wedge(dx[2],dx[3])),scale(x[1],wedge(dx[0],dx[2])))
    assert derivative(derivative(alpha,x),x)=={}
    lhs=derivative(wedge(alpha,beta),x)
    rhs=add(wedge(derivative(alpha,x),beta),scale(-1,wedge(alpha,derivative(beta,x))))
    assert lhs==rhs
    assert wedge(dx[0],dx[0])=={}
    assert wedge(dx[0],dx[2])==scale(-1,wedge(dx[2],dx[0]))
    assert clean({(2,0):3,(0,2):3})=={}
    # Missing graded minus is rejected on a nonzero witness.
    wrong=add(wedge(derivative(alpha,x),beta),wedge(alpha,derivative(beta,x)))
    assert lhs!=wrong
    for n in [2,3,4]:
        E=s.Matrix(n,n,lambda i,j:(i+1)*(j+2)+(7 if i==j else 0))
        B=E.inv()
        for k in range(n+1):
            for rows in combinations(range(n),k):
                for cols in combinations(range(n),k):
                    value=densitized_inverse_minor(E,rows,cols)
                    assert s.simplify(value-E.det()*B.extract(rows,cols).det())==0
                    assert densitized_inverse_minor(E,rows,cols,normalized=True)==value/s.Integer(factorial(k))
    t=s.symbols('t')
    singular=s.diag(t,3,5)
    assert densitized_inverse_minor(singular,(0,),(0,))==15
    assert densitized_inverse_minor(singular,(0,1),(0,1),normalized=True)==s.Rational(5,2)
    assert densitized_inverse_minor(singular,(0,1),(0,1))!=s.Rational(5,2)
    try:
        densitized_inverse_minor(singular,(1,0),(0,1))
    except ValueError:
        pass
    else:
        raise AssertionError('unsorted-index foil was accepted')
    print('PASS: exterior identities, graded-sign foil, all complementary minors and singular continuation')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selftest',action='store_true',required=True)
    parser.parse_args()
    selftest()
