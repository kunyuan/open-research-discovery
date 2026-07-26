# Verifier

Implement the verification profile declared in `problem.yaml`.

- For `machine-checkable` or `hybrid`, prefer exact integer, rational,
  finite-field, SAT, proof-assistant, interval, or independently replayable
  checks.
- For `llm-reviewable`, replace the marker in `review.md` with bounded source
  context, ordered checks, rejection conditions, and a required verdict format.
- For `expert-review`, state the review boundary and do not imply that
  `make verify` establishes any conclusion outside the encoded contract.

The verifier must:

- reject malformed and adversarial candidates;
- avoid network access;
- distinguish validity from novelty;
- print a concise machine-readable outcome;
- return zero only when the local discovery contract is satisfied.

For datasets, experiments, simulations, and models, also pin provenance,
versions, units, data splits, controls, uncertainty rules, and the exact
population or parameter regime covered by acceptance.
