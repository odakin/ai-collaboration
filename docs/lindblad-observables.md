# Finite-matrix Lindblad observable checks

[lindblad_observables.py](../scripts/lindblad_observables.py) evaluates the
observable derivative of a supplied finite Lindblad model. It requires NumPy.
The scientific comparison protocol is
[the observable/state/generator audit](../../claude-config/conventions/scientific-computing.md#observable-state-generator-audit).
Rates, channels, preparation, and observables remain inputs chosen by the caller.

For a channel with generator

    D[L]rho = L rho L† - {L†L, rho}/2,

the adjoint applied to an observable O is

    D[L]† O = L† O L - {L†L, O}/2.

For the intensity observable I = gamma L†L under the single generator gamma D[L],

    d<I>/dt = gamma² <L†[L†,L]L>.

The sign uses the complete operator sandwich in the original state, or the
commutator in the state after L acts. An initial-state mean commutator alone
does not supply this sign. With several channels or a Hamiltonian, use
`observable_derivative` on the intensity observable so every contribution is
retained. These algebraic checks do not establish that a reservoir is Markovian.

## API

| Function | Output |
|---|---|
| `dissipator_adjoint(L, O)` | Rate-free adjoint dissipator applied to O. |
| `observable_derivative(O, channels, hamiltonian)` | Full observable derivative; channels are `(rate, L)` pairs. |
| `intensity_derivative_operator(L, rate)` | Single-channel intensity derivative operator, including both rate factors. |
| `expectation(rho, O)` | Complex trace pairing; density-state validity remains the caller's responsibility. |
| `restrict_operator(O, V)` | V† O V for orthonormal columns V. |

Compute products and derivatives in the full finite model before restricting
to a support basis. Projecting L first generally changes its commutators and
the generator. A truncated oscillator has a boundary term in its commutator;
check the occupied and dynamically accessible subspace and enlarge the cutoff.
Finite-matrix agreement alone does not prove an unbounded-operator identity or
uniform convergence of states that follow a moving cutoff.

The selftest checks primal/adjoint trace duality, the intensity identity, and
foils for a dropped operator, a missing rate factor, and cutoff contamination.
It uses synthetic matrices and standard finite ladder operators. It contains
no project inputs or model-specific findings.

    python3 scripts/lindblad_observables.py --selftest

Independent project checkers remain unchanged as evidence. Compare this library
to their outputs in a separate integration check; replacing both independent
implementations with this same library does not preserve their independence.
