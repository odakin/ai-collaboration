# Binary state discrimination: reusable certificates and scope

This note derives finite-dimensional results from definitions. Numerical anchors
are in [state_discrimination.py](../scripts/state_discrimination.py), a NumPy-only
companion to [gpt_measurements.py](../scripts/gpt_measurements.py). Neither library
can certify an arbitrary infinite state cone by sampling it. Source-specific
theorem numbers, quotations and verdicts belong in the caller's evidence ledger.

## Error, lower bound and equality

Let the trace-one Hermitian states be rho0 and rho1, with prior p in [0,1].
Outcome E guesses state 0. Write X = p rho0 − (1−p) rho1 = P−N for its positive
and negative parts. Then error = p − Tr(XE). For an arbitrary Hermitian E with
minimum eigenvalue a and maximum b, set r=b−a and r'=a+b. Direct expansion gives

```
L = 1/2 − r ||X||_1/2 − (2p−1)(r'−1)/2
error − L = Tr[P(bI−E)] + Tr[N(E−aI)] >= 0.
```

Both terms are traces of products of PSD matrices. Equality holds exactly when
range(P) is in the b-eigenspace of E and range(N) is in the a-eigenspace.
Zero eigenspaces of X impose no condition, and a=b is allowed. One can prove
the zero-product step using Tr(AB)=||A^(1/2) B^(1/2)||_HS² for PSD A,B.
Thus the inequality and its equality characterization have separate certificates.
`slack_terms` returns the two terms; `equality_residual` tests the two support
conditions numerically. Its `reverse=True` option deliberately swaps the extrema
for a negative control. Eigenvalues within TOL of zero are ignored by this
diagnostic; it is not an exact rank determination.

These algebraic identities require normalization and Hermiticity, not positivity
of the states or E. To interpret error as a physical probability, separately
prove that the states and both effects E,I−E belong to the chosen GPT. Agreement
of probabilities on the tested pair does not establish global effect membership.

## Quantum optimum and biased qubits

For density matrices and 0<=E<=I, maximize Tr(XE) with the positive spectral
projector of X. The optimum error is (1−||X||_1)/2. When X is positive definite,
E=I is optimal; when negative definite, E=0 is optimal. On ker X any effect is
permitted subject to the POVM bounds. Do not require an optimal effect to have
both eigenvalues 0 and 1 in these definite cases.

For rho(r)=(I+r·sigma)/2, define t=2p−1 and v=p r0−(1−p)r1. The eigenvalues of
X are (t±|v|)/2, hence

```
||X||_1/2 = max(|t|, |v|)/2
optimal quantum error = [1 − max(|t|, |v|)]/2.
```

The formula for the norm holds for every real Bloch vector; interpreting the
second line as a quantum optimum requires |r0|,|r1|<=1. Dropping the |t| branch
fails even for identical states with an unequal prior.

## Interior perturbations and a closed-cone characterization

Consider a full-dimensional trace-normalized cone C contained in the PSD cone,
with the full dual effect interval [0,I] in C*. If a binary effect E has r>1,
choose a normalized interior state sigma and rank-one projectors Qmax,Qmin in
the extremal eigenspaces of E. For sufficiently small epsilon>0,
rho±=sigma±epsilon(Qmax−Qmin) belong to C. At equal priors,

```
||rho+ − rho−||_1 = 4 epsilon
error = 1/2 − epsilon r < 1/2 − epsilon = quantum comparison.
```

Conversely r<=1 makes the general bound at p=1/2 at least the quantum bound.
The interior argument, normalization and trace factors should be established
before choosing an epsilon numerically.

If C is also closed and C is a proper subset of PSD, separate a missing PSD
matrix from C to obtain W in C* with a negative eigenvalue. Its maximum eigenvalue
b is positive: otherwise its pairing with a positive-definite interior state of
C would be negative. Then E=W/b is in C*, I−E is PSD and hence in C*, and r(E)>1.
The preceding perturbation violates the quantum bound. Therefore a closed,
full-dimensional C contained in PSD whose full dual measurements satisfy the
bound for all pairs must equal PSD. This argument needs neither a numerical SDP
nor a spectral equality claim from another proof.

Closedness is load-bearing. The cone {0} union {positive-definite matrices} is
convex, pointed and full-dimensional, with dual PSD. Every allowed measurement
is a POVM and every normalized state obeys the quantum bound, yet this cone
omits all nonzero singular PSD matrices. Its closure is PSD. More generally,
dual inequalities recover the closure, not necessarily the original cone.
An order-unit assumption means **for each** dual vector some finite bound exists;
one uniform bound for all vectors is impossible in a nonzero vector space.

## Coordinates, embeddings and a cube certificate

With a compact normalized base and dimension d², choose a trace-compatible linear
coordinate map into d-dimensional Hermitian matrices. The traceless parts of its
normalized states are bounded. Shrinking those parts sufficiently around I/d
makes every state positive definite while preserving invertibility. Coordinate
representation alone does not give this state-inclusion property; compactness
supplies the uniform bound. Adding a classical ancilla to obtain square dimension
changes the model, so a conclusion about the enlarged system is not automatically
a conclusion about the original system.

An invertible trace-preserving map f sends states to f(rho) and effects to
(f*)^(-1)(E); probabilities are invariant. Ambient trace distances need not be.
For example f_s(X)=sX+(1−s)Tr(X)I/d, 0<s<=1, shrinks traceless differences by s.
Even the same quantum model has a different comparison with the ambient quantum
bound after this coordinate change. A property B(f) of a fixed representation
must be distinguished from the model property **there exists f with A(f) and B(f)**,
where A requires all embedded states to be density matrices.

State inclusion cannot simply be dropped. The Bloch cube has normalized states
|r_j|<=s. For E=alpha I+b·sigma, global validity on this cube is exactly

```
s ||b||_1 <= min(alpha, 1−alpha).
```

At s=1 every allowed effect is a POVM, because ||b||_2<=||b||_1. All pairs obey
the ambient spectral lower bound, but some cube states are not PSD. The closed
cone over a cube has eight extreme rays and cannot be linearly isomorphic to
the qubit PSD cone. At s=1/sqrt(3), every state is PSD. The valid effect
(I+sigma_z/s)/2 perfectly distinguishes the states at ±s z; the ambient quantum
comparison is (1−s)/2>0. The cube therefore isolates the role of A as well as
the dependence on f. `cube_effect` uses the global dual inequality; vertex
probabilities are a second check, complete here because the cube is a polytope.

## Base norm, supporting effects and intrinsic formulations

For a closed proper generating cone with compact normalized base S and order
unit u, the unit ball of its base norm N is conv(S union −S). Thus

```
N(x) = min {a+b : x=a rho−b sigma, a,b>=0, rho,sigma in S}
     = max {f(x) : −u <= f <= u}.
```

Compactness supplies attainment. Zero coefficients require separate treatment;
never normalize a zero positive or negative part. A norming functional gives
f(rho)=1 and f(sigma)=−1 when both coefficients are positive, so (u+f)/2 is a
globally valid distinguishing effect. Endpoint values alone are insufficient:
for the qubit states |0> and |+>, diag(1,−1) takes values 1 and 0 but is negative
on |1>, so it is not an effect on the full quantum state space.

Here is a second proof route for a closed C contained in PSD and generating the
full ambient Hermitian space (so every Hermitian matrix has a base decomposition). Suppose the
operational distance N(rho−sigma)/2 equals ||rho−sigma||_1/2 on S. For any
quantum density matrix tau, take a minimum decomposition tau=a rho−b sigma;
a−b=1. If b>0, its norming functional perfectly distinguishes rho and sigma.
The assumed distance equality implies orthogonal PSD supports. Then
(1+b)rho−b sigma is negative on the nonzero support of sigma, contradicting
tau>=0. If b=0, a=1 and tau=rho is already in S. Hence C=PSD. This proof handles
the zero branch explicitly and requires support functionals bounded on all of S.

An intrinsic structural restatement uses an affine isometry between (S,N/2)
and the quantum density body with half trace distance, or an order-unit-preserving
linear isometry of base-norm spaces. For a closed cone, C={x:N(x)=u(x)}, so this
recovers its order structure. It still specifies quantum geometry. The universal
GPT identity min_error=(1−N(rho−sigma)/2)/2 at equal priors, by itself, selects
no particular theory.

## Bipartite examples and reproducibility

Partial transpose on subsystem B satisfies
<a,b|Gamma_B(T)|a,b>=<a,conj(b)|T|a,conj(b)> for Hermitian T. Thus T>=0 implies
Gamma_B(T) is nonnegative on every product vector, although it need not be PSD.
This is a global certificate on the separable cone. `partial_transpose` supports
unequal subsystem dimensions and its selftest checks this product identity and
involution. Identify which summand is PSD and which is a partial transpose of a
PSD operator; those are different properties. Perfect discrimination (error=0)
also does not imply saturation of a general lower bound that may be negative.

Run `python3 scripts/state_discrimination.py --selftest`. Tests include independent
probability sums, PSD slack certificates, biased and trivial optima, Bloch norm
comparisons, deliberately reversed equality conditions, invalid quantum inputs,
cube duality, and product-vector transpose identities. These finite checks anchor
the formulas; the universal arguments above supply their mathematical scope.
For check/foil execution use the canonical campaign reporter. A foil succeeds only
when its intended assertion rejects the mutation; an unrelated crash is a failure.
