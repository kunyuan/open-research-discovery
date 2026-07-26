# Verifier

Implement the problem-specific acceptance boundary declared in `problem.yaml`.

- `solution-review.md` tells the Solution Reviewer how to judge the submitted
  result after a solver finishes.
- `ci.md` describes optional automation and its exact limits.
- `check.py` contains substantive machine checks only when they really exist.

The verifier must:

- judge only the submitted result, not the solver's hidden reasoning process;
- reject malformed and adversarial submissions;
- avoid network access;
- distinguish local validity from novelty and current openness;
- print a concise machine-readable outcome;
- return zero for substantive acceptance only when every encoded condition
  passes.

For datasets, experiments, simulations, and models, pin provenance, versions,
units, data splits, controls, uncertainty rules, and the exact population or
parameter regime covered by acceptance.
