# `gaia.engine.bayes`

gaia.engine.bayes - hypothesis-data inference verbs.

Public API surface (6 symbols), introspected from `gaia.engine.bayes.__all__`. Private (`_`-prefixed) members are filtered, matching the Pages-site mkdocstrings config.

## `BayesInference`

_class_

```python
BayesInference(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>) -> None
```

Bayes-family reasoning record (marker base class).

## `Model`

_class_

```python
Model(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, hypothesis: 'Claim | None' = None, observable: 'Variable | None' = None, distribution: 'Distribution | None' = None, helper: 'Claim | None' = None) -> None
```

Predictive model: ties a hypothesis to a distribution over an observable.

## `ModelCompare`

_class_

```python
ModelCompare(label: 'str | None' = None, rationale: 'str' = '', background: 'list[Knowledge]' = <factory>, metadata: 'dict[str, Any]' = <factory>, warrants: 'list[Claim]' = <factory>, helper: 'Claim | None' = None, models: 'tuple[Claim, ...]' = (), data: 'tuple[Claim, ...]' = (), exclusivity: 'str' = 'exhaustive_pairwise_complement', precomputed: 'Any | None' = None, log_likelihoods: 'dict[Claim, float]' = <factory>) -> None
```

Equal-positioned list of competing predictive models.

## `PrecomputedLikelihoods`

_class_

```python
PrecomputedLikelihoods(content: 'str | None' = None, *, log_likelihoods: 'dict[Claim, float] | None' = None, diagnostics: 'dict[str, Any] | None' = None, solver: 'str' = '', label: 'str | None' = None, metadata: 'dict[str, Any] | None' = None, **kwargs: 'Any') -> 'None'
```

Externally computed log-likelihoods packaged as a Claim.

Attributes:
----------
log_likelihoods:
    Mapping from hypothesis :class:`Claim` (the original objects passed
    to :func:`gaia.engine.bayes.model`) to ``log P(data | H_i)``. Same
    key shape as the legacy ``compare(precomputed=...)`` dict.
diagnostics:
    Solver-specific convergence and provenance fields. Opaque to Gaia;
    consumed by ``gaia audit`` rules and reviewers. Recommended keys:
    ``r_hat_max``, ``ess_min``, ``divergences``, ``seed``,
    ``model_spec_hash``.
solver:
    Free-form solver label, e.g. ``"pymc-nuts-4000"`` or ``"custom"``.

## `compare`

_function_

```python
compare(data: 'Claim | list[Claim] | tuple[Claim, ...]', *, models: 'list[Claim] | tuple[Claim, ...]', background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None, exclusivity: 'str' = 'exhaustive_pairwise_complement', precomputed: 'dict[Claim, float] | PrecomputedLikelihoods | None' = None, metadata: 'dict[str, Any] | None' = None) -> 'Claim'
```

Compare observed data against an equal-positioned list of models.

Returns the comparison helper Claim. The helper carries
``metadata["comparison"]`` describing the exclusivity contract and,
after compilation, the per-hypothesis log-likelihood table.

Point vs composite hypotheses
-----------------------------
Use a point distribution such as ``Binomial(n, p=v)`` only when the
hypothesis really fixes the parameter value. If the hypothesis
commits to a direction or region instead, use a compound
distribution such as ``BetaBinomial(n, alpha, beta)``.

Comparing a point hypothesis with a diffuse alternative such as
``BetaBinomial(n, alpha=1, beta=1)`` can produce extreme Bayes
factors from one Gaia observation claim when the data are only
slightly off the point. Run ``gaia sdk`` for the local SDK reference
and cheat sheet; see the Bayes Hypothesis Types guide in the Gaia
docs (``docs/for-users/bayes-hypothesis-types.md``) for the full
treatment.

Exclusivity contracts
---------------------
``exclusivity`` controls what structural-action relationship Gaia
asserts between the compared hypotheses. **The choice of contract
materially changes the posterior** because it changes the set of
joint hypothesis states the factor graph is allowed to occupy:

* ``"exhaustive_pairwise_complement"`` (**default**, 2 models only):
  ensure ``exclusive(m1, m2)`` is in the package — exactly one of
  the two hypotheses is true. Posterior odds equal the
  (Cromwell-clamped) likelihood ratio. This is the standard
  Bayesian model-selection contract and the right default when the
  author intends "which of these two competing models best explains
  the data". Currently rejected for ``len(models) > 2`` until an
  N-ary Exclusive operator is implemented; use
  ``"pairwise_contradiction"`` (at-most-one semantics) meanwhile.

* ``"pairwise_contradiction"`` (≥2 models): ensure
  ``contradict(m_i, m_j)`` is in the package for every pair.
  At-most-one is true; an "all false" joint state is allowed. The
  hardcoded ``α=0.5`` anchor in each ``infer`` factor's CPT then
  assigns substantial mass to that joint state, **diluting
  model-comparison posterior odds**. Use this only when you
  genuinely believe the listed models may all be wrong and want the
  posterior to reflect that.

Deduplication
-------------
``compare()`` does not blindly create new structural actions —
before emitting it scans the active package for an existing
same-type relation covering the same hypothesis pair:

* **No same-type external declaration**: ``compare()`` emits the
  auto-generated structural action matching ``exclusivity``.
* **Same-type external declaration already in place** (e.g.
  external ``exclusive(m1, m2)`` and ``exclusivity=
  "exhaustive_pairwise_complement"``): ``compare()`` skips
  emission. The external author's helper Claim and rationale are
  preserved.
* **Different-type external declaration** (e.g. external
  ``contradict(m1, m2)`` while ``compare()`` wants to emit
  ``exclusive(m1, m2)``): both actions coexist. They are logically
  consistent — ``Exclusive`` implies ``Contradict``, so the joint
  factor-graph constraint is just ``Exclusive``. The IR's own
  structural-relation consistency checks (the D2 "same operator +
  same args + distinct conclusions" rule and friends) are the
  authority on whether the combined graph is legal, not the DSL.

The previous ``exclusivity="none"`` escape hatch (which suppressed
auto-generation entirely) is no longer accepted: same-type dedup
serves the same purpose without letting authors silently bypass
any contract.

## `model`

_function_

```python
model(hypothesis: 'Claim', *, observable: 'Variable', distribution: 'Distribution', background: 'list[Knowledge] | None' = None, rationale: 'str' = '', label: 'str | None' = None, metadata: 'dict[str, Any] | None' = None) -> 'Claim'
```

Declare a predictive model for one hypothesis and observable.
