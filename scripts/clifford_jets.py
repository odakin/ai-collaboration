#!/usr/bin/env python3
"""Operator identities on a curved background as exact polynomial identities: a real Clifford algebra over a sparse integer polynomial ring, geometry derived from a Riemann-normal vierbein, second-order operators by the product rule, basis jets of the field acted on; --selftest.

Why: an operator identity (a squared Dirac-type operator as a Laplacian plus an endomorphism, a commutator as a
curvature) is decided by applying both sides to the jets of the field they act on.  The reasoning (why a finite set of
basis jets exposes every coefficient, why the geometry is derived and not transcribed) is in
conventions/physics-verification-cycle.md#operator-identity-on-jets; this module is the engine.  What it fixes:

  * Every field (gamma^mu, the spin connection, an external endomorphism) is an element of the real algebra spanned by
    the 2^D monomials gamma_{a1} ... gamma_{ak}, a1 < ... < ak, held as a list of sparse polynomials indexed by a bitmask.
    The multiplication table is read off the gamma matrices you pass in, and closure with real signs is checked
    (closes()), so the computation stays over Z with no i.  Components of a fixed-degree field stay sparse in this basis.
  * Coefficients are integers: scale the curvature tensor (24 clears the 1/6 of the normal-coordinate vierbein and the
    1/2 of the Christoffel symbols; exact_div asserts every division).  Measured: matrices over Gaussian rationals, with
    the products rebuilt per jet, were too slow to finish; the integer ring with products formed once per background
    decides the same identities in seconds to a minute.
  * The vierbein is e^a_mu = delta + eps f^a_mu, f^a_mu = -(1/6) R_{a alpha mu beta} x^alpha x^beta (Riemann normal
    coordinates, symmetric gauge), Euclidean; eps counts the order in the curvature and everything is truncated at
    O(eps^2).  Inverse vierbein, metric, Christoffel symbols and spin connection are computed from e.
  * nablat_mu = d_mu + Ohat_mu with Ohat_mu = W_mu + X_mu, W_mu = (1/4) omega_{ab mu} gamma^a gamma^b, X_mu = whatever
    bind_connection() is given.  Products Ohat_mu Ohat_nu are formed once per background, so a jet costs only the
    action of the operator on it.

It is a separate module from exact_jets.py on purpose.  exact_jets holds rational Taylor data of tensors at one point
(NumPy object arrays, random numbers in the fields): the right tool for scalar identities decided pointwise.  Here the
identity must hold at every order in x and for symbolic external fields, with operators acting on jets, in a polynomial
ring over Z (sympy.polys): the two share no data structure.

Usage (a Dirac-type operator with an external endomorphism; see the selftest for the bare Dirac case)
  from clifford_jets import CliffordJets, NormalGeometry, random_curvature_int
  alg = CliffordJets(gammas, one, extra=symbols)      # sympy matrices with {gamma_a, gamma_b} = 2 delta_ab
  geo = NormalGeometry(alg, random_curvature_int(rng, alg.dim))
  geo.bind_connection(X)                              # X_mu, or nothing for the bare spin connection
  for m, psi in alg.scalar_jets(2):                   # each residual is a Clifford element acting on the spinor jet
      lhs = geo.dirac(geo.dirac(alg.cscalar(psi)))
      rhs = alg.cadd(geo.laplacian(psi), alg.cscale(E, psi))
  python3 clifford_jets.py --selftest
"""
from __future__ import annotations

import itertools
import random
import sys

import sympy as sp
from sympy.polys.domains import ZZ
from sympy.polys.rings import ring


class CliffordJets:
    """The polynomial ring (x^mu, eps, extra symbols) over Z and the real Clifford algebra with polynomial components."""

    def __init__(self, gammas, one, extra=()):
        self.dim = D = len(gammas)
        self.nb = 1 << D
        self.xs = sp.symbols(f"x0:{D}", real=True)
        self.eps_symbol = sp.Symbol("eps")
        self.ring, *gens = ring([*self.xs, self.eps_symbol, *extra], ZZ)
        self.x = gens[:D]
        self.eps = gens[D]
        self.extra = gens[D + 1:]
        self.ieps = D
        self.zero = self.ring.zero
        self.one = self.ring.one
        self.mat = []
        for S in range(self.nb):
            M = one
            for a in range(D):
                if S >> a & 1:
                    M = M * gammas[a]
            self.mat.append(M)
        self.sign = [[0] * self.nb for _ in range(self.nb)]
        for S in range(self.nb):
            for T in range(self.nb):
                P = (self.mat[S] * self.mat[T]).applyfunc(sp.expand)
                K = S ^ T
                if P == self.mat[K]:
                    self.sign[S][T] = 1
                elif P == -self.mat[K]:
                    self.sign[S][T] = -1
        self.mono1 = [1 << a for a in range(D)]       # gamma_a

    def closes(self):
        """True when the monomials close under multiplication with signs +-1 (a real algebra, no i)."""
        return all(s in (1, -1) for row in self.sign for s in row)

    # --- polynomials
    def const(self, c):
        return self.ring(ZZ(int(c)))

    def trunc(self, p):
        """Drop O(eps^2)."""
        d = {m: c for m, c in p.terms() if m[self.ieps] < 2}
        return self.ring.from_dict(d) if d else self.zero

    def exact_div(self, p, k):
        """p / k for a polynomial all of whose coefficients are divisible by k (asserted)."""
        d = {}
        for m, c in p.terms():
            q, r = divmod(int(c), k)
            assert r == 0, f"coefficient {c} not divisible by {k}"
            d[m] = q
        return self.ring.from_dict(d) if d else self.zero

    def split_orders(self, polys):
        """{(eps order, x degree): number of monomials} over a list of polynomials."""
        out: dict = {}
        for p in polys:
            for m, _ in p.terms():
                key = (m[self.ieps], sum(m[:self.dim]))
                out[key] = out.get(key, 0) + 1
        return out

    def scalar_jets(self, maxdeg):
        """[(index tuple, monomial)] of degree <= maxdeg; a k-th order operator is exposed by the jets of degree <= k."""
        out = []
        for deg in range(maxdeg + 1):
            for m in itertools.combinations_with_replacement(range(self.dim), deg):
                mono = self.one
                for i in m:
                    mono = mono * self.x[i]
                out.append((m, mono))
        return out

    # --- Clifford elements: lists of nb polynomials
    def czero(self):
        return [self.zero] * self.nb

    def cscalar(self, p):
        out = self.czero()
        out[0] = p
        return out

    def cadd(self, A, B, c=1):
        return [A[i] + c * B[i] for i in range(self.nb)]

    def cscale(self, A, s):
        return [s * A[i] for i in range(self.nb)]

    def cmul(self, A, B):
        out = self.czero()
        for S in range(self.nb):
            if A[S] == 0:
                continue
            for T in range(self.nb):
                if B[T] == 0:
                    continue
                out[S ^ T] = out[S ^ T] + self.sign[S][T] * A[S] * B[T]
        return out

    def cdiff(self, A, mu):
        return [p.diff(self.x[mu]) for p in A]

    def ctrunc(self, A):
        return [self.trunc(p) for p in A]

    def ciszero(self, A):
        return all(p == 0 for p in A)

    def cmono(self, bits, p):
        """p x (the monomial with bitmask bits)."""
        out = self.czero()
        out[bits] = p
        return out

    def gamma_pair(self, a, b, p):
        """p x gamma_a gamma_b as a Clifford element (a != b)."""
        return self.cmono(self.mono1[a] ^ self.mono1[b], self.sign[self.mono1[a]][self.mono1[b]] * p)

    def cvector(self, comps):
        """sum_a comps[a] gamma_a."""
        out = self.czero()
        for a in range(self.dim):
            out[self.mono1[a]] = comps[a]
        return out

    def cmatrix(self, A, subs_):
        """Clifford element -> sympy matrix after substituting subs_ into the components."""
        M = sp.zeros(*self.mat[0].shape)
        for S in range(self.nb):
            if A[S] != 0:
                M += (A[S].subs(subs_) if subs_ else A[S]).as_expr() * self.mat[S]
        return M.applyfunc(sp.expand)


def random_curvature_int(rng, dim=4, nterms=12, scale=24):
    """Algebraic curvature tensor sum_k c_k (u_k ^ v_k)_{ab} (u_k ^ v_k)_{cd} with integer u, v, c, times scale.
    A sum of squares of simple bivectors has pair antisymmetry, pair symmetry and the first Bianchi identity."""
    Rm = [[[[0] * dim for _ in range(dim)] for _ in range(dim)] for _ in range(dim)]
    for _ in range(nterms):
        u = [rng.randint(-2, 2) for _ in range(dim)]
        v = [rng.randint(-2, 2) for _ in range(dim)]
        B = [[u[a] * v[b] - u[b] * v[a] for b in range(dim)] for a in range(dim)]
        c = rng.randint(-3, 3)
        for a, b, cc, d in itertools.product(range(dim), repeat=4):
            Rm[a][b][cc][d] += scale * c * B[a][b] * B[cc][d]
    return [[[[sp.Integer(v) for v in row] for row in blk] for blk in slab] for slab in Rm]


def is_algebraic_curvature(Rm):
    """Pair antisymmetry, pair symmetry and the first Bianchi identity."""
    dim = len(Rm)
    for i, j, k, l in itertools.product(range(dim), repeat=4):
        if not (Rm[i][j][k][l] == -Rm[j][i][k][l] == -Rm[i][j][l][k] and Rm[i][j][k][l] == Rm[k][l][i][j]):
            return False
        if Rm[i][j][k][l] + Rm[i][k][l][j] + Rm[i][l][j][k] != 0:
            return False
    return True


class NormalGeometry:
    """Geometry derived from the Riemann-normal vierbein at O(eps), and the second-order operator of a bound connection."""

    def __init__(self, alg, Rm):
        self.alg = alg
        self.Rm = Rm
        A = alg
        IDX = range(A.dim)
        x, eps = A.x, A.eps
        zero, const, exact_div, trunc = A.zero, A.const, A.exact_div, A.trunc
        Ri = [[[[int(Rm[i][j][k][l]) for l in IDX] for k in IDX] for j in IDX] for i in IDX]
        self.Ri = Ri
        self.Ric = [[sum(Rm[c][b][c][n] for c in IDX) for n in IDX] for b in IDX]
        self.Rs = sum(self.Ric[b][b] for b in IDX)
        delta = lambda i, j: A.one if i == j else zero
        # vierbein, inverse vierbein, metric, inverse metric, Christoffel symbols (all at O(eps)); f = -(1/6) R x x
        f = [[exact_div(sum((const(-Ri[a][al][mu][be]) * x[al] * x[be] for al in IDX for be in IDX if Ri[a][al][mu][be]), zero), 6)
              for mu in IDX] for a in IDX]
        self.f = f
        self.e = [[delta(a, mu) + eps * f[a][mu] for mu in IDX] for a in IDX]
        self.Einv = [[delta(a, mu) - eps * f[mu][a] for mu in IDX] for a in IDX]
        h = [[f[mu][nu] + f[nu][mu] for nu in IDX] for mu in IDX]
        self.g = [[delta(mu, nu) + eps * h[mu][nu] for nu in IDX] for mu in IDX]
        self.ginv = [[delta(mu, nu) - eps * h[mu][nu] for nu in IDX] for mu in IDX]
        self.Gam = [[[trunc(exact_div(eps * (h[nu][lam].diff(x[mu]) + h[mu][lam].diff(x[nu]) - h[mu][nu].diff(x[lam])), 2))
                      for nu in IDX] for mu in IDX] for lam in IDX]
        # spin connection omega_{ab mu} = e^a_nu nabla_mu E_b^nu
        self.om = [[[trunc(sum((self.e[a][nu] * (self.Einv[b][nu].diff(x[mu])
                                                 + sum((self.Gam[nu][mu][lam] * self.Einv[b][lam] for lam in IDX), zero))
                                for nu in IDX), zero))
                     for mu in IDX] for b in IDX] for a in IDX]
        # W_mu = (1/4) omega_{ab mu} gamma^a gamma^b = (1/2) sum_{a<b} omega_{ab mu} gamma_a gamma_b
        self.W = []
        for mu in IDX:
            Wm = A.czero()
            for a in IDX:
                for b in range(a + 1, A.dim):
                    if self.om[a][b][mu] != 0:
                        Wm = A.cadd(Wm, A.gamma_pair(a, b, exact_div(self.om[a][b][mu], 2)))
            self.W.append(Wm)
        self.Gup = [A.ctrunc(A.cvector([self.Einv[a][mu] for a in IDX])) for mu in IDX]        # gamma^mu = E_a^mu gamma^a
        self.Glow = [A.ctrunc(A.cvector([self.e[a][mu] for a in IDX])) for mu in IDX]          # gamma_mu = e^a_mu gamma_a

    def riemann_matches_input(self):
        """The Riemann tensor of this metric at O(eps), from the Christoffel symbols, equals the input (constant in x).
        False for an input that is not an algebraic curvature tensor: the normal-coordinate vierbein assumes one."""
        A = self.alg
        for rho, sig, mu, nu in itertools.product(range(A.dim), repeat=4):
            lin = self.Gam[rho][nu][sig].diff(A.x[mu]) - self.Gam[rho][mu][sig].diff(A.x[nu])
            if lin - A.eps * A.const(self.Ri[rho][sig][mu][nu]) != 0:
                return False
        return True

    # --- derivatives
    def nablaM(self, M, mu):
        """Covariant derivative of an endomorphism-valued field (spin connection by commutator)."""
        A = self.alg
        return A.ctrunc(A.cadd(A.cadd(A.cdiff(M, mu), A.cmul(self.W[mu], M)), A.cmul(M, self.W[mu]), -1))

    def nabla(self, v, mu):
        return self.alg.cadd(self.alg.cdiff(v, mu), self.alg.cmul(self.W[mu], v))

    def dirac(self, v):
        """gamma^mu nabla_mu v (add an endomorphism in the caller for a Dirac-type operator)."""
        A = self.alg
        out = A.czero()
        for mu in range(A.dim):
            out = A.cadd(out, A.cmul(self.Gup[mu], self.nabla(v, mu)))
        return A.ctrunc(out)

    # --- the second-order operator of nablat = d + W + X
    def bind_connection(self, X=None, products=None):
        """Form Ohat_mu = W_mu + X_mu, its derivatives, Ohat_mu Ohat_nu and the operator coefficients of
        g^{mu nu}(nablat_mu nablat_nu - Gamma^lam_{mu nu} nablat_lam) = g^{mu nu} d_mu d_nu + C1_lam d_lam + C0, once per
        background.  products = [[X_mu X_nu]] if the caller already holds them."""
        A = self.alg
        IDX = range(A.dim)
        if X is None:
            X = [A.czero() for _ in IDX]
        if products is None:
            products = [[A.ctrunc(A.cmul(X[mu], X[nu])) for nu in IDX] for mu in IDX]
        self.Ohat = [A.cadd(self.W[mu], X[mu]) for mu in IDX]
        self.dOhat = [[A.cdiff(self.Ohat[nu], mu) for nu in IDX] for mu in IDX]
        self.OO = [[A.ctrunc(A.cadd(A.cadd(A.cadd(A.cmul(self.W[mu], self.W[nu]), A.cmul(self.W[mu], X[nu])),
                                           A.cmul(X[mu], self.W[nu])), products[mu][nu])) for nu in IDX] for mu in IDX]
        self.C1 = []
        for lam in IDX:
            c1 = A.czero()
            for mu in IDX:
                if self.ginv[mu][lam] != 0:
                    c1 = A.cadd(c1, A.cscale(self.Ohat[mu], 2 * self.ginv[mu][lam]))
            gam = A.zero
            for mu in IDX:
                for nu in IDX:
                    if self.ginv[mu][nu] != 0 and self.Gam[lam][mu][nu] != 0:
                        gam = gam + self.ginv[mu][nu] * self.Gam[lam][mu][nu]
            c1 = A.cadd(c1, A.cscalar(gam), -1)
            self.C1.append(A.ctrunc(c1))
        c0 = A.czero()
        for mu in IDX:
            for nu in IDX:
                if self.ginv[mu][nu] == 0:
                    continue
                term = A.cadd(self.dOhat[mu][nu], self.OO[mu][nu])
                for lam in IDX:
                    if self.Gam[lam][mu][nu] != 0:
                        term = A.cadd(term, A.cscale(self.Ohat[lam], self.Gam[lam][mu][nu]), -1)
                c0 = A.cadd(c0, A.cscale(term, self.ginv[mu][nu]))
        self.C0 = A.ctrunc(c0)

    def second(self, psi, mu, nu):
        """nablat_mu (nablat_nu psi) on a scalar jet psi by the product rule."""
        A = self.alg
        out = A.cscalar(psi.diff(A.x[nu]).diff(A.x[mu]))
        out = A.cadd(out, A.cscale(self.dOhat[mu][nu], psi))
        out = A.cadd(out, A.cscale(self.Ohat[nu], psi.diff(A.x[mu])))
        out = A.cadd(out, A.cscale(self.Ohat[mu], psi.diff(A.x[nu])))
        return A.cadd(out, A.cscale(self.OO[mu][nu], psi))

    def laplacian(self, psi):
        """g^{mu nu}(nablat_mu nablat_nu - Gamma^lam_{mu nu} nablat_lam) on a scalar jet psi."""
        A = self.alg
        IDX = range(A.dim)
        lap = A.zero
        for mu in IDX:
            for nu in IDX:
                if self.ginv[mu][nu] != 0:
                    lap = lap + self.ginv[mu][nu] * psi.diff(A.x[mu]).diff(A.x[nu])
        out = A.cscalar(lap)
        for lam in IDX:
            out = A.cadd(out, A.cscale(self.C1[lam], psi.diff(A.x[lam])))
        out = A.cadd(out, A.cscale(self.C0, psi))
        return A.ctrunc(out)


# ------------------------------------------------------------------ selftest (bare Dirac operator, textbook anchors)
def _euclidean_gammas():
    """Hermitian 4 x 4 gamma matrices with {gamma_a, gamma_b} = 2 delta_ab, from Kronecker products of Pauli matrices."""
    s1 = sp.Matrix([[0, 1], [1, 0]])
    s2 = sp.Matrix([[0, -sp.I], [sp.I, 0]])
    s3 = sp.Matrix([[1, 0], [0, -1]])
    kron = sp.kronecker_product
    return [kron(s1, sp.eye(2)), kron(s2, sp.eye(2)), kron(s3, s1), kron(s3, s2)], sp.eye(4)


def selftest() -> int:
    failed: list = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failed.append(label)

    gammas, one = _euclidean_gammas()
    alg = CliffordJets(gammas, one)
    D = alg.dim
    check("the gamma matrices satisfy the Euclidean Clifford relation",
          all((gammas[a] * gammas[b] + gammas[b] * gammas[a]).applyfunc(sp.expand) == 2 * int(a == b) * one for a in range(D) for b in range(D)))
    check("the 16 monomials close with real signs", alg.closes())
    swaps = lambda S, T: sum(bin(S >> (a + 1)).count("1") for a in range(D) if T >> a & 1)
    check("the sign table read off the matrices is the anticommutation count",
          all(alg.sign[S][T] == (-1) ** swaps(S, T) for S in range(alg.nb) for T in range(alg.nb)))
    bad = CliffordJets([sp.Matrix([[0, 1], [1, 0]]), sp.Matrix([[0, 1], [1, 0]]) + sp.eye(2)], sp.eye(2))
    check("matrices that are not a Clifford set are refused by closes() (foil)", not bad.closes())

    rng = random.Random(1)
    Rm = random_curvature_int(rng, D)
    check("random_curvature_int: an algebraic curvature tensor", is_algebraic_curvature(Rm))
    geo = NormalGeometry(alg, Rm)
    geo.bind_connection()
    check("normal-coordinate vierbein: Riemann of the derived metric = the input at O(eps)", geo.riemann_matches_input())
    Rbad = [[[[Rm[i][j][k][l] for l in range(D)] for k in range(D)] for j in range(D)] for i in range(D)]
    Rbad[0][1][2][3] += 24
    Rbad[1][0][2][3] -= 24
    Rbad[0][1][3][2] -= 24
    Rbad[1][0][3][2] += 24
    Rbad[2][3][0][1] += 24
    Rbad[3][2][0][1] -= 24
    Rbad[2][3][1][0] -= 24
    Rbad[3][2][1][0] += 24
    check("a tensor that breaks the first Bianchi identity is not algebraic (foil)", not is_algebraic_curvature(Rbad))
    check("... and the normal-coordinate vierbein does not reproduce it (foil)", not NormalGeometry(alg, Rbad).riemann_matches_input())
    check("spin connection: antisymmetric, omega_{ab mu} = -(1/2) eps R_{ab mu beta} x^beta",
          all(geo.om[a][b][mu] + geo.om[b][a][mu] == 0
              and 2 * geo.om[a][b][mu] + alg.eps * sum((alg.const(geo.Ri[a][b][mu][be]) * alg.x[be] for be in range(D)), alg.zero) == 0
              for a in range(D) for b in range(D) for mu in range(D)))

    # Lichnerowicz: Dslash^2 = nabla^2 - R/4, and [nabla_mu, nabla_nu] = (1/4) R_{ab mu nu} gamma^a gamma^b, on basis jets
    E = alg.cscalar(alg.exact_div(alg.const(-geo.Rs) * alg.eps, 4))
    jets = alg.scalar_jets(2)
    fail_sq, fail_comm, fail_foil = 0, 0, 0
    for _, psi in jets:
        lhs = geo.dirac(geo.dirac(alg.cscalar(psi)))
        res = alg.ctrunc(alg.cadd(lhs, alg.cadd(geo.laplacian(psi), alg.cscale(E, psi)), -1))
        fail_sq += not alg.ciszero(res)
        foil = alg.ctrunc(alg.cadd(lhs, geo.laplacian(psi), -1))
        fail_foil += not alg.ciszero(alg.cadd(foil, alg.cscale(E, psi), -1))
        for mu in range(D):
            for nu in range(mu + 1, D):
                comm = alg.cadd(geo.second(psi, mu, nu), geo.second(psi, nu, mu), -1)
                want = alg.czero()
                for a in range(D):
                    for b in range(a + 1, D):
                        if geo.Ri[a][b][mu][nu]:
                            want = alg.cadd(want, alg.gamma_pair(a, b, alg.exact_div(alg.const(geo.Ri[a][b][mu][nu]) * alg.eps, 2)))
                fail_comm += not alg.ciszero(alg.ctrunc(alg.cadd(comm, alg.cscale(want, psi), -1)))
    check(f"Lichnerowicz: Dslash^2 psi = (nabla^2 - R/4) psi on all {len(jets)} scalar jets x the spinor components, at every order in x", fail_sq == 0)
    check("the residual without -R/4 is exactly -(R/4) eps psi (foil with an exact value)", fail_foil == 0 and geo.Rs != 0)
    check("[nabla_mu, nabla_nu] psi = (1/4) eps R_{ab mu nu} gamma^a gamma^b psi on all jets and pairs", fail_comm == 0)
    # an external X is carried by the product rule: a covariantly trivial shift X_mu = d_mu(phi) scalar
    phi = sum((alg.x[i] * alg.x[i] for i in range(D)), alg.zero)
    X = [alg.cscalar(phi.diff(alg.x[mu])) for mu in range(D)]
    geoX = NormalGeometry(alg, Rm)
    geoX.bind_connection(X)
    ok = True
    for _, psi in jets:
        # nablat psi with X = d phi is e^-phi nabla e^phi: the commutator does not see a pure gauge X
        for mu in range(D):
            for nu in range(mu + 1, D):
                ok = ok and alg.ciszero(alg.ctrunc(alg.cadd(alg.cadd(geoX.second(psi, mu, nu), geoX.second(psi, nu, mu), -1),
                                                            alg.cadd(geo.second(psi, mu, nu), geo.second(psi, nu, mu), -1), -1)))
    check("bind_connection: a pure-gauge scalar X leaves the commutator unchanged", ok)
    ok = True
    for _, psi in jets:
        lap = alg.czero()
        for mu in range(D):
            for nu in range(D):
                if geoX.ginv[mu][nu] == 0:
                    continue
                term = geoX.second(psi, mu, nu)
                for lam in range(D):
                    if geoX.Gam[lam][mu][nu] != 0:
                        first = alg.cadd(alg.cscalar(psi.diff(alg.x[lam])), alg.cscale(geoX.Ohat[lam], psi))
                        term = alg.cadd(term, alg.cscale(first, geoX.Gam[lam][mu][nu]), -1)
                lap = alg.cadd(lap, alg.cscale(term, geoX.ginv[mu][nu]))
        ok = ok and alg.ciszero(alg.ctrunc(alg.cadd(lap, geoX.laplacian(psi), -1)))
    check("laplacian: the coefficients formed once per background equal the definition through second()", ok)
    second = random_curvature_int(rng, D)
    geo2 = NormalGeometry(alg, second)
    geo2.bind_connection()
    E2 = alg.cscalar(alg.exact_div(alg.const(-geo2.Rs) * alg.eps, 4))
    ok = all(alg.ciszero(alg.ctrunc(alg.cadd(geo2.dirac(geo2.dirac(alg.cscalar(psi))), alg.cadd(geo2.laplacian(psi), alg.cscale(E2, psi)), -1)))
             for _, psi in jets)
    check("Lichnerowicz on a second random curvature tensor", ok)
    check("split_orders counts by (eps order, x degree)", alg.split_orders([alg.eps * alg.x[0] + alg.x[1] * alg.x[2]]) == {(1, 1): 1, (0, 2): 1})
    try:
        alg.exact_div(alg.const(3), 2)
        check("exact_div refuses a division that does not close", False)
    except AssertionError:
        check("exact_div refuses a division that does not close", True)

    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
