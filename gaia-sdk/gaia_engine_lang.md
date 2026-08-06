# `gaia.engine.lang`

Gaia Lang — Python DSL for knowledge authoring.

Public API surface (97 symbols), introspected from `gaia.engine.lang.__all__`. Private (`_`-prefixed) members are filtered, matching the Pages-site mkdocstrings config.

## `ArithOp`

_class_

```python
ArithOp(op: 'str', left: 'Any', right: 'Any') -> None
```

An arithmetic operation between two Terms.

## `Associate`

_class_

```python
Associate(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, helper: 'Claim | None' = None, a: 'Claim | None' = None, b: 'Claim | None' = None, p_a_given_b: 'float' = 0.5, p_b_given_a: 'float' = 0.5, pattern: 'str | None' = None) -> None
```

Symmetric probabilistic association between two Claims.

## `Beta`

_function_

```python
Beta(content: 'str', *, alpha: 'Any', beta: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Beta-distributed continuous quantity with a name.

Beta shape parameters ``alpha`` and ``beta`` are dimensionless.

## `BetaBinomial`

_function_

```python
BetaBinomial(content: 'str', *, n: 'Any', alpha: 'Any', beta: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Beta-Binomial-distributed discrete quantity with a name.

Predictive distribution of ``Binomial(n, p)`` integrated over
``p ~ Beta(alpha, beta)``. All three parameters are dimensionless.
The closed-form uniform marginal ``BetaBinomial(n, 1, 1)`` is the
canonical diffuse reference: ``P(k) = 1 / (n + 1)`` for ``k ∈ [0, n]``.

## `Binomial`

_function_

```python
Binomial(content: 'str', *, n: 'Any', p: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Binomial-distributed discrete quantity with a name.

``n`` and ``p`` are dimensionless.

## `Bool`

_other_

```python
Bool
```

A built-in typed sort. Construction is sealed once the module finishes loading.

## `BoolExpr`

_class_

```python
BoolExpr(op: 'ComparisonOp', left: 'Any', right: 'Any') -> None
```

Boolean proposition over Distribution objects.

Created by Distribution comparison operators (``k > 1e-3``,
``y == baseline + slope * x``). ``claim(content, expr)`` accepts a BoolExpr as the
second argument and lowers it to claim metadata so the compiler can
compute the resulting prior via the underlying distribution's CDF (for
inequality predicates). Equality / equation predicates are preserved in
metadata with author/default priors; constraint lowering is future work.

The :meth:`__bool__` override raises so accidental Python control-flow use
(``if k > 1e-3: ...``) surfaces immediately rather than silently always
evaluating to True (the dataclass would otherwise be truthy).

## `CandidateRelation`

_class_

```python
CandidateRelation(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, claims: 'tuple[Claim, ...]' = (), pattern: 'str | None' = None, status: 'str' = 'hypothesis') -> None
```

Marks a hypothesized relation that has not been formalized yet.

## `Cauchy`

_function_

```python
Cauchy(content: 'str', *, mu: 'Any', gamma: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Cauchy-distributed continuous quantity with a name.

``mu`` and ``gamma`` share the location/scale unit of the underlying
random variable.

## `ChiSquared`

_function_

```python
ChiSquared(content: 'str', *, df: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Chi-squared distributed continuous quantity with a name.

``df`` is dimensionless.

## `Claim`

_class_

```python
Claim(content: 'str | None' = None, *, prior: 'float | None' = None, from_actions: 'list[Any] | None' = None, formula: 'Any' = None, kind: 'ClaimKind' = <ClaimKind.GENERAL: 'general'>, **kwargs: 'Any') -> 'None'
```

Proposition with prior. Participates in BP.

## `ClaimAtom`

_class_

```python
ClaimAtom(claim: 'Claim') -> None
```

A reference to another Claim's truth — the bridge from formula land to claim graph.

## `ClaimKind`

_class_

```python
ClaimKind(*values)
```

Shape discriminator for the structured-content of a Claim (spec §4.2).

GENERAL      — default; formula optional, no structural commitments
PARAMETER    — asserts a Variable takes a specific value (Equals(var, const))
QUANTIFIED   — top-level quantifier (Forall/Exists) in formula

NOT a "role" (hypothesis/prediction/observation-as-evidence) — those live
on action graph nodes. Observation is an Observe action, not a Claim kind.
NOT helper-claim metadata.

## `Compose`

_class_

```python
Compose(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, name: 'str' = '', version: 'str' = '', inputs: 'tuple[Knowledge | str, ...]' = (), actions: 'tuple[Action | str, ...]' = (), conclusion: 'Claim | None' = None) -> None
```

Action-level composition of child actions into a reviewable DAG.

## `Composition`

_class_

```python
Composition(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, name: 'str' = '', version: 'str' = '', inputs: 'tuple[Knowledge | str, ...]' = (), actions: 'tuple[Action | str, ...]' = (), conclusion: 'Claim | None' = None) -> None
```

Action-level composition of child actions into a reviewable DAG.

## `Compute`

_class_

```python
Compute(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, conclusion: 'Claim | None' = None, given: 'tuple[Claim, ...]' = (), fn: 'Callable[..., Any] | None' = None, code_hash: 'str | None' = None) -> None
```

Deterministic code execution.

## `Constant`

_class_

```python
Constant(value: 'Any', primitive: 'PrimitiveType') -> None
```

A primitive literal value, validated against its declared PrimitiveType.

## `Contradict`

_class_

```python
Contradict(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, a: 'Claim | None' = None, b: 'Claim | None' = None, helper: 'Claim | None' = None) -> None
```

Declares two Claims contradictory.

## `Decompose`

_class_

```python
Decompose(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, whole: 'Claim | None' = None, parts: 'tuple[Claim, ...]' = (), formula: 'Any' = None) -> None
```

Declares a whole Claim equivalent to a formula over atomic Claims.

## `DependsOn`

_class_

```python
DependsOn(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, conclusion: 'Claim | None' = None, given: 'tuple[Claim, ...]' = ()) -> None
```

Marks unformalized dependencies for a conclusion.

## `Derive`

_class_

```python
Derive(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, conclusion: 'Claim | None' = None, given: 'tuple[Claim, ...]' = ()) -> None
```

Logical derivation.

## `DerivedDistribution`

_class_

```python
DerivedDistribution(op: 'ArithmeticOp', left: 'Any', right: 'Any') -> None
```

Arithmetic combination of distributions / scalars (e.g. ``baseline + slope * x``).

Used as the right-hand side of an :class:`Equation` proposition. Carries no
runtime sampling logic — it is a syntactic placeholder retained in
equation metadata for audit and future constraint lowering.

Constants (Python ``int`` / ``float`` / ``Quantity``) and other
DerivedDistributions may appear on either operand position.

## `Distribution`

_class_

```python
Distribution(content: 'str', *, impl: '_BaseDistribution', format: 'str' = 'markdown', **kwargs: 'Any') -> 'None'
```

Knowledge-wrapped continuous quantity with a probability distribution.

Use the family-specific factories (:func:`Normal`, :func:`LogNormal`,
:func:`Beta`, etc.) rather than constructing this directly — they wrap the
matching ``gaia.engine.bayes.distributions._BaseDistribution`` subclass into
a Distribution carrying a content string + identity.

The wrapped computational object is available as ``.impl`` and exposes
``logpdf`` / ``logpmf`` / ``cdf`` / ``support`` / ``model_dump`` via thin
delegating properties on this class.

## `Domain`

_class_

```python
Domain(content: 'str', *, members: 'list[Any]', format: 'str' = 'markdown', **kwargs: 'Any') -> 'None'
```

A user-declared, finite, enumerable typed sort.

Subclasses Knowledge so it carries identity, provenance, and metadata.
Lang-only: does NOT enter the package's IR-bound knowledge map.

## `Equal`

_class_

```python
Equal(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, a: 'Claim | None' = None, b: 'Claim | None' = None, helper: 'Claim | None' = None) -> None
```

Declares two Claims equivalent.

## `Equals`

_class_

```python
Equals(left: 'Any', right: 'Any') -> None
```

Term equality formula.

## `Exclusive`

_class_

```python
Exclusive(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, a: 'Claim | None' = None, b: 'Claim | None' = None, helper: 'Claim | None' = None) -> None
```

Declares two Claims form a closed binary partition.

## `Exists`

_class_

```python
Exists(variable: 'Variable', body: 'Any') -> None
```

Existential quantifier binding a free Variable in a Formula body.

## `Exponential`

_function_

```python
Exponential(content: 'str', *, rate: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create an Exponential-distributed continuous quantity with a name.

``rate`` may be a bare scalar or a :class:`gaia.unit.Quantity` (typically
``1 / time``). The corresponding random variable's unit is the inverse of
``rate``'s unit; for predicate / observe consistency we record that
inverse unit as the distribution's canonical ``metadata["unit"]``.

## `Forall`

_class_

```python
Forall(variable: 'Variable', body: 'Any') -> None
```

Universal quantifier binding a free Variable in a Formula body.

## `Formula`

_class_

```python
Formula(*args, **kwargs)
```

Marker protocol — a truth-valued AST node.

## `FunctionApp`

_class_

```python
FunctionApp(symbol: 'FunctionSymbol', args: 'tuple[Any, ...]') -> None
```

Application of a FunctionSymbol to a tuple of Term arguments.

## `FunctionSymbol`

_class_

```python
FunctionSymbol(name: 'str', arg_domains: 'tuple[PrimitiveType | Domain, ...]', result_domain: 'PrimitiveType | Domain') -> None
```

Declaration of a user function symbol like ``E: Particle → Real``.

## `Gamma`

_function_

```python
Gamma(content: 'str', *, alpha: 'Any', rate: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Gamma-distributed continuous quantity with a name.

``alpha`` is dimensionless; ``rate`` may carry the inverse unit of the
underlying random variable (typically ``1 / x``).

## `Greater`

_class_

```python
Greater(left: 'Any', right: 'Any') -> None
```

Greater-than relation over Term operands.

## `GreaterEqual`

_class_

```python
GreaterEqual(left: 'Any', right: 'Any') -> None
```

Greater-than-or-equal relation over Term operands.

## `Iff`

_class_

```python
Iff(left: 'Any', right: 'Any') -> None
```

Logical equivalence between two Formula operands.

## `Implies`

_class_

```python
Implies(antecedent: 'Any', consequent: 'Any') -> None
```

Logical implication from antecedent Formula to consequent Formula.

## `Infer`

_class_

```python
Infer(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, helper: 'Claim | None' = None, hypothesis: 'Claim | None' = None, evidence: 'Claim | None' = None, given: 'tuple[Claim, ...]' = (), p_e_given_h: 'float | Claim' = 0.5, p_e_given_not_h: 'float | Claim | None' = 0.5, p_e_given_not_h_defaulted: 'bool' = False) -> None
```

Bayesian inference: P(E|H) update.

## `Knowledge`

_class_

```python
Knowledge(content: 'str', format: 'str' = 'markdown', type: 'str' = 'knowledge', title: 'str | None' = None, background: 'list[Knowledge]' = <factory>, parameters: 'list[dict[str, Any]]' = <factory>, provenance: 'list[dict[str, str]]' = <factory>, metadata: 'dict[str, Any]' = <factory>, label: 'str | None' = None, strategy: 'Any | None' = None) -> None
```

Base knowledge node. Plain text plus metadata.

## `Land`

_class_

```python
Land(operands: 'tuple[Any, ...]') -> None
```

Logical conjunction over two or more Formula operands.

## `Less`

_class_

```python
Less(left: 'Any', right: 'Any') -> None
```

Less-than relation over Term operands.

## `LessEqual`

_class_

```python
LessEqual(left: 'Any', right: 'Any') -> None
```

Less-than-or-equal relation over Term operands.

## `Lnot`

_class_

```python
Lnot(operand: 'Any') -> None
```

Logical negation of a Formula operand.

## `LogNormal`

_function_

```python
LogNormal(content: 'str', *, mu: 'Any', sigma: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a LogNormal-distributed continuous quantity with a name.

The LogNormal parameters live in log-space; ``mu`` and ``sigma`` must be
dimensionless scalars. Encode the unit of the underlying random variable
in the content string (e.g. ``LogNormal("k / s^-1", mu=log(1e-3), sigma=2)``).

## `Lor`

_class_

```python
Lor(operands: 'tuple[Any, ...]') -> None
```

Logical disjunction over two or more Formula operands.

## `MaterializationLink`

_class_

```python
MaterializationLink(scaffold: 'Scaffold', by: 'tuple[GaiaGraph, ...]', label: 'str | None' = None, rationale: 'str' = '', metadata: 'dict[str, Any]' = <factory>) -> None
```

Bookkeeping link from scaffold to the formal graph records that handle it.

## `Nat`

_other_

```python
Nat
```

A built-in typed sort. Construction is sealed once the module finishes loading.

## `Normal`

_function_

```python
Normal(content: 'str', *, mu: 'Any', sigma: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Normal-distributed continuous quantity with a name.

``mu`` and ``sigma`` may both be bare scalars or both be
:class:`gaia.unit.Quantity` values sharing a unit; mixing them raises.

## `NotEquals`

_class_

```python
NotEquals(left: 'Any', right: 'Any') -> None
```

Term inequality formula.

## `Note`

_class_

```python
Note(content: 'str', *, format: 'str' = 'markdown', **kwargs: 'Any') -> 'None'
```

Non-probabilistic contextual material. Does not enter BP.

## `Observe`

_class_

```python
Observe(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, conclusion: 'Claim | None' = None, given: 'tuple[Claim, ...]' = ()) -> None
```

Empirical observation or measurement.

## `Poisson`

_function_

```python
Poisson(content: 'str', *, rate: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Poisson-distributed discrete quantity with a name.

``rate`` is the dimensionless expected count for the interval encoded by
the quantity name. Pass a bare scalar; unit-typed rates are rejected.

## `PredicateSymbol`

_class_

```python
PredicateSymbol(name: 'str', arg_domains: 'tuple[PrimitiveType | Domain, ...]') -> None
```

Declaration of a user predicate symbol like ``Stable: Particle → Bool``.

## `PrimitiveType`

_class_

```python
PrimitiveType(name: 'str', accept: 'Callable[[object], bool]') -> 'None'
```

A built-in typed sort. Construction is sealed once the module finishes loading.

## `Probability`

_other_

```python
Probability
```

A built-in typed sort. Construction is sealed once the module finishes loading.

## `Question`

_class_

```python
Question(content: 'str', **kwargs: 'Any') -> 'None'
```

Open inquiry. Does not enter BP.

## `Real`

_other_

```python
Real
```

A built-in typed sort. Construction is sealed once the module finishes loading.

## `RoleOccurrence`

_class_

```python
RoleOccurrence(claim: 'Claim', role: 'str', action: 'Action', action_type: 'str', action_label: 'str | None' = None, path: 'tuple[str, ...]' = (), source: 'str' = 'explicit_field') -> None
```

A claim role at a specific occurrence in an authored action.

## `StudentT`

_function_

```python
StudentT(content: 'str', *, df: 'Any', mu: 'Any', sigma: 'Any', **kwargs: 'Any') -> 'Distribution'
```

Create a Student-t distributed continuous quantity with a name.

``df`` is dimensionless; ``mu`` and ``sigma`` share the location/scale
unit of the underlying random variable.

## `Term`

_class_

```python
Term(*args, **kwargs)
```

Marker protocol. A Term is a value-bearing expression node.

## `UserPredicate`

_class_

```python
UserPredicate(symbol: 'PredicateSymbol', args: 'tuple[Any, ...]') -> None
```

Application of a user-declared PredicateSymbol to typed Term arguments.

## `Variable`

_class_

```python
Variable(*, symbol: 'str', domain: 'PrimitiveType | Domain', value: 'Any | None' = None, unit: 'str | None' = None, content: 'str | None' = None, format: 'str' = 'markdown', **kwargs: 'Any') -> 'None'
```

A typed term referenceable by formulas, models, and actions.

Subclasses Knowledge for identity, provenance, metadata. Carries a symbol
used in formulas, a domain (PrimitiveType or user-declared Domain), and an
optional bound value. Binding semantics (CONSTANT / FREE / BOUND_BY_CLAIM)
are inferred by Milestone B's compiler; this class stores only authored data.

Lang-only: does NOT enter the package's IR-bound knowledge map (spec §2.4).

## `artifact`

_function_

```python
artifact(*, kind: 'str', source: 'str | None' = None, locator: 'str | None' = None, path: 'str | None' = None, caption: 'str | None' = None, description: 'str | None' = None, media_type: 'str | None' = None, content: 'str | None' = None, title: 'str | None' = None) -> 'Note'
```

Create a note carrying structured artifact metadata.

## `associate`

_function_

```python
associate(a: 'Any', b: 'Any', *, p_a_given_b: 'float', p_b_given_a: 'float', pattern: 'str | None' = None, background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Claim'
```

Declare a symmetric probabilistic association. Returns an association helper Claim.

``a`` and ``b`` may be any Boolean-valued expression (``Claim``,
``ClaimAtom``, Formula node, or ``BoolExpr``); non-``Claim`` inputs are
lifted to helper Claims at the verb boundary per RFC #703.

## `candidate_relation`

_function_

```python
candidate_relation(*, claims: 'list[Any] | tuple[Any, ...]', pattern: 'str | None' = None, background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None, metadata: 'dict[str, Any] | None' = None) -> 'CandidateRelation'
```

Record a hypothesized relation without triggering formal semantics.

Every entry of ``claims`` may be any Boolean-valued expression
(``Claim``, ``ClaimAtom``, Formula node, or ``BoolExpr``);
non-``Claim`` inputs are lifted to helper Claims at the verb boundary
per RFC #703.

## `claim`

_function_

```python
claim(content: 'str', proposition: 'BoolExpr | None' = None, *, title: 'str | None' = None, format: 'str' = 'markdown', background: 'list[Knowledge] | None' = None, parameters: 'list[dict[str, Any]] | None' = None, provenance: 'list[dict[str, str]] | None' = None, prior: 'float | None' = None, formula: 'Any' = None, kind: 'ClaimKind' = <ClaimKind.GENERAL: 'general'>, tolerance: 'float | None' = None, **metadata: 'Any') -> 'Claim'
```

Declare a scientific assertion.

Three authoring shapes:

1. **Prose claim** — ``claim("Heliocentric model is correct.", prior=0.8)``.
   The proposition is conveyed in natural language. The optional ``prior``
   keyword is a low-priority shortcut routed through ``register_prior()``
   with ``source_id="claim_inline"``.
2. **Predicate claim** — ``claim("Reaction is fast", k > 1e-2)``. The
   second positional argument is a :class:`BoolExpr` produced by
   comparing a :class:`Distribution` against a constant. The compiler
   registers a CDF-derived prior record for inequality predicates.
   See :class:`gaia.engine.lang.Distribution` for how to declare the
   underlying continuous quantity.
3. **Formula claim** — ``claim(content, formula=Forall(...))`` for the
   predicate-logic surface (unchanged from v0.5).

The ``tolerance`` keyword applies only when ``proposition`` is an equation
(``lhs == rhs``). PR1 stores equation metadata and a neutral default prior;
equation constraint lowering is deferred.

## `compose`

_function_

```python
compose(*, name: 'str', version: 'str', background: 'list[Knowledge] | None' = None, warrants: 'list[Claim] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Callable[[Callable[..., Claim]], Callable[..., Claim]]'
```

Decorate a function as a Gaia action composition template.

## `composition`

_function_

```python
composition(*, name: 'str', version: 'str', background: 'list[Knowledge] | None' = None, warrants: 'list[Claim] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Callable[[Callable[..., Claim]], Callable[..., Claim]]'
```

Decorate a function as a Gaia action composition template.

## `compute`

_function_

```python
compute(conclusion_type: 'type[Claim] | Callable[..., Any]', *, fn: 'Callable[..., Any] | None' = None, given: 'Claim | tuple[Claim, ...] | list[Claim] | None' = (), background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Claim | Callable[..., Claim]'
```

Deterministic computation.

Used either as ``compute(ResultClaim, fn=..., given=...)`` or as ``@compute``.

## `contradict`

_function_

```python
contradict(a: 'Any', b: 'Any', *, background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Claim'
```

Declare two Claims contradictory. Returns a contradiction helper Claim.

``a`` and ``b`` may be any Boolean-valued expression (``Claim``,
``ClaimAtom``, Formula node, or ``BoolExpr``); non-``Claim`` inputs are
lifted to helper Claims at the verb boundary per RFC #703.

## `decompose`

_function_

```python
decompose(whole: 'Any', *, parts: 'tuple[Claim, ...] | list[Claim]', formula: 'Any', background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None, metadata: 'dict[str, Any] | None' = None) -> 'Claim'
```

Declare ``whole`` equivalent to ``formula`` over atomic ``parts``.

``whole`` may be any Boolean-valued expression (``Claim``,
``ClaimAtom``, Formula node, or ``BoolExpr``); non-``Claim`` inputs are
lifted to a helper Claim at the verb boundary per RFC #703.

``parts`` is NOT lifted: each entry must be an atomic ``Claim`` that
already appears in ``formula``'s :class:`ClaimAtom` leaves, since the
verb's structural invariant is a bijection between ``parts`` and the
atoms of ``formula``. Lifting a Formula in ``parts`` would create a
new helper Claim whose id is not in that bijection.

## `depends_on`

_function_

```python
depends_on(conclusion: 'Any', *, given: 'Any', background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None, metadata: 'dict[str, Any] | None' = None) -> 'DependsOn'
```

Record unformalized load-bearing dependencies for a Claim.

``conclusion`` and every entry of ``given`` may be any Boolean-valued
expression (``Claim``, ``ClaimAtom``, Formula node, or ``BoolExpr``);
non-``Claim`` inputs are lifted to helper Claims at the verb boundary
per RFC #703.

## `derive`

_function_

```python
derive(conclusion: 'Any', *, given: 'Any' = (), background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Claim'
```

Logical derivation. Returns the conclusion Claim.

``conclusion`` may be a ``Claim``, a ``str`` (which creates a fresh
Claim from the content), or any Boolean-valued expression
(``ClaimAtom`` / Formula / ``BoolExpr``) that lifts to a helper Claim
at the verb boundary per RFC #703.

Every entry of ``given`` is similarly lifted: a Boolean-valued
expression becomes a helper Claim; non-Claim non-Boolean-valued values
raise an educational :class:`TypeError`.

## `equal`

_function_

```python
equal(a: 'Any', b: 'Any', *, background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Claim'
```

Declare two Claims equivalent. Returns an equivalence helper Claim.

``a`` and ``b`` may be any Boolean-valued expression (``Claim``,
``ClaimAtom``, Formula node, or ``BoolExpr``); non-``Claim`` inputs are
lifted to helper Claims at the verb boundary per RFC #703.

## `equals`

_function_

```python
equals(left: 'Any', right: 'Any') -> 'Equals'
```

Create an equality formula.

## `exclusive`

_function_

```python
exclusive(a: 'Any', b: 'Any', *, background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Claim'
```

Declare two Claims as a closed binary partition. Returns an XOR helper Claim.

``a`` and ``b`` may be any Boolean-valued expression (``Claim``,
``ClaimAtom``, Formula node, or ``BoolExpr``); non-``Claim`` inputs are
lifted to helper Claims at the verb boundary per RFC #703.

## `exists`

_function_

```python
exists(variable: 'Variable', body: 'Any') -> 'Exists'
```

Create an existential quantifier over a free variable.

## `export`

_function_

```python
export(*items: 'str | Knowledge') -> 'list[str]'
```

Return root ``__all__`` names for a package's public Knowledge surface.

The helper is intentionally small: it returns a plain ``list[str]`` and
stores no hidden export state. Passing strings is equivalent to writing the
names directly. Passing a ``Knowledge`` object resolves the object's public
name from the caller's module or local scope, which keeps ``__all__`` close
to normal Python public-API conventions while avoiding string typos.

## `figure`

_function_

```python
figure(*, source: 'str | None' = None, locator: 'str | None' = None, path: 'str | None' = None, caption: 'str | None' = None, description: 'str | None' = None, media_type: 'str | None' = None, content: 'str | None' = None, title: 'str | None' = None) -> 'Note'
```

Create a figure artifact note.

## `forall`

_function_

```python
forall(variable: 'Variable', body: 'Any') -> 'Forall'
```

Create a universal quantifier over a free variable.

## `iff`

_function_

```python
iff(left: 'Any', right: 'Any') -> 'Iff'
```

Create an equivalence formula.

## `implies`

_function_

```python
implies(antecedent: 'Any', consequent: 'Any') -> 'Implies'
```

Create an implication formula.

## `infer`

_function_

```python
infer(evidence: 'Claim | str | None' = None, *args: 'Any', hypothesis: 'Claim | None' = None, given: 'Claim | tuple[Claim, ...] | list[Claim] | None' = (), background: 'list[Knowledge] | None' = None, p_e_given_h: 'float | Claim | None' = None, p_e_given_not_h: 'float | Claim | None' = 0.5, rationale: 'str' = '', label: 'str | None' = None, **legacy_kwargs: 'Any') -> 'Claim | Strategy'
```

Bayesian inference. Returns the evidence Claim.

The canonical v6 shape is ``infer(evidence, hypothesis=..., ...)``. The old
v5 ``infer([premises], conclusion, ...)`` form is preserved as a deprecated
compatibility path.

## `is_formula`

_function_

```python
is_formula(obj: 'object') -> 'bool'
```

Return whether an object is explicitly tagged as a Formula node.

## `is_term`

_function_

```python
is_term(obj: 'object') -> 'bool'
```

Strict check — only objects explicitly tagged as terms qualify.

## `land`

_function_

```python
land(*operands: 'Any') -> 'Land'
```

Create a logical conjunction formula.

## `lnot`

_function_

```python
lnot(operand: 'Any') -> 'Lnot'
```

Create a logical negation formula.

## `lor`

_function_

```python
lor(*operands: 'Any') -> 'Lor'
```

Create a logical disjunction formula.

## `materialize`

_function_

```python
materialize(scaffold: 'Scaffold', *, by: 'GaiaGraph | Claim | str | list[GaiaGraph | Claim | str] | tuple[GaiaGraph | Claim | str, ...]', rationale: 'str' = '', label: 'str | None' = None, metadata: 'dict[str, Any] | None' = None) -> 'MaterializationLink'
```

Record a checked link from scaffold to formal graph records.

## `note`

_function_

```python
note(content: 'str', *, title: 'str | None' = None, format: 'str' = 'markdown', **metadata: 'Any') -> 'Note'
```

Declare non-probabilistic contextual material.

## `observe`

_function_

```python
observe(conclusion: 'Any', *, value: 'Any' = <object object at 0x10a610860>, error: 'Any' = None, given: 'Claim | tuple[Claim, ...] | list[Claim] | None' = (), background: 'list[Knowledge] | None' = None, source_refs: 'list[str] | None' = None, rationale: 'str' = '', label: 'str | None' = None) -> 'Claim'
```

Empirical observation.

Three authoring shapes:

1. **Discrete claim observation** — ``observe(my_claim)``. A Boolean-valued
   expression such as ``a & b`` is lifted to an explicit helper Claim first.
   A no-premise observation pins the conclusion to ``1 - CROMWELL_EPS``.
   Use ``given=`` to record a conditional observation that does not pin the
   conclusion.
2. **Continuous quantity observation** — ``observe(distribution,
   value=v, error=σ)``. Records a measurement event for a
   :class:`Distribution`-typed quantity. Returns a freshly minted
   :class:`Claim` representing the observation event (pinned to
   ``1 - CROMWELL_EPS`` since the measurement was made), with metadata
   linking back to the underlying distribution. The compiler reads this
   linkage for audit and future posterior-CDF lowering. The current
   predicate-prior lowering still uses the Distribution's prior CDF and
   emits a warning when an observation targets the same Distribution.

   ``value`` is the measured numeric value; ``error`` is either ``None``
   for a noise-free observation, a scalar interpreted as the Gaussian
   additive standard deviation, or a :class:`Distribution` for a
   custom noise model.

3. **Variable observation (v0.6 unified-bayes path)** —
   ``observe(variable, value=v, error=σ)``. Records a measurement event
   for a primitive :class:`Variable` (the kind that appears as the
   observable of a Bayes predictive model). Writes the unified
   ``metadata["observation"]`` schema consumed by
   :func:`gaia.engine.bayes.compare`. Scalar ``error`` is sugared into
   an anonymous ``Normal(mu=0, sigma=error)`` so noise is always either
   ``None`` or a :class:`Distribution` Knowledge node.

## `parameter`

_function_

```python
parameter(variable: 'Variable', value: 'Any', *, content: 'str | None' = None, describe: 'str | None' = None, title: 'str | None' = None, format: 'str' = 'markdown', background: 'list[Knowledge] | None' = None, provenance: 'list[dict[str, str]] | None' = None, prior: 'float | None' = None, label: 'str | None' = None, metadata: 'dict[str, Any] | None' = None) -> 'Claim'
```

Declare that a primitive Variable takes a concrete value.

## `question`

_function_

```python
question(content: 'str', *, title: 'str | None' = None, format: 'str' = 'markdown', **metadata: 'Any') -> 'Question'
```

Declare a research question. No probability, no BP participation.

## `register_prior`

_function_

```python
register_prior(claim: 'Any', value: 'float', *, justification: 'str', source_id: 'str' = 'user_priors', created_at: 'datetime | None' = None) -> 'None'
```

Register a prior probability for a claim from a named source.

This is the canonical (and after v0.5, the only) way to attach a prior to
a Claim. The author writes register_prior calls in ``priors.py`` (auto-
imported by ``gaia build compile``) or anywhere else in the package; engines and
reviewers use the same API with an appropriate ``source_id``.

Args:
    claim: The Claim instance to attach the prior to.
    value: Prior probability. Must be inside the Cromwell bounds
        ``[CROMWELL_EPS, 1 - CROMWELL_EPS]`` — values outside this range
        are rejected with ValueError (no silent clamping; engines writing
        extreme values almost always indicate a bug).
    justification: Required non-empty rationale string. Empty or
        whitespace-only justifications are rejected.
    source_id: Source identifier; defaults to ``"user_priors"`` for
        author-written priors. Engines, reviewers, and agents must pass
        an explicit ``source_id`` so the ResolutionPolicy can rank them.
        Common namespaces: ``"user_priors"``, ``"continuous_inference"``,
        ``"reviewer_*"``, ``"calibration_*"``, ``"agent_*"``,
        ``"evidence_factor_*"``.
    created_at: Optional explicit timestamp. Defaults to ``datetime.now(UTC)``.
        Provide an explicit value for reproducible package builds or when
        registering historical priors.

Raises:
    TypeError: If ``claim`` is not a Claim instance, if a Boolean-valued
        expression is passed instead of an explicit Claim, or if ``value``
        is not a numeric scalar (booleans are explicitly rejected to catch
        mistakes like ``register_prior(c, True)``).
    ValueError: If ``value`` is outside Cromwell bounds, ``source_id`` is
        empty/whitespace, or ``justification`` is empty/whitespace.

Examples:
    Author writes in ``priors.py``::

        from gaia.engine.lang import register_prior
        from . import aristotle_model, medium_model

        register_prior(aristotle_model, 0.5,
                       justification="Neutral before the thought experiment.")
        register_prior(medium_model, 0.5,
                       justification="Neutral before the thought experiment.")

    Reviewer writes alternative priors in ``priors_reviewer_alice.py``::

        register_prior(aristotle_model, 0.05,
                       source_id="reviewer_alice",
                       justification="Tied-body argument is decisive against A.")

## `roles_for_claim`

_function_

```python
roles_for_claim(claim: 'Claim', graph: 'ActionGraph', *, include_background: 'bool' = True, include_warrants: 'bool' = True) -> 'tuple[RoleOccurrence, ...]'
```

Return all authored action roles for ``claim``.

## `roles_for_package`

_function_

```python
roles_for_package(graph: 'ActionGraph', *, include_background: 'bool' = True, include_warrants: 'bool' = True) -> 'dict[Claim, tuple[RoleOccurrence, ...]]'
```

Index authored action roles by claim identity.
