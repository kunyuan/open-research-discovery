# Problem Schema v1.0

This contract describes one open research problem that can be solved by an
Agent or a human researcher and reviewed by an Agent, CI, or a human Reviewer.

## JSON format

```json
{
  "schema_version": "1.0",
  "problem_id": "problem-id",
  "parent_problem_id": null,
  "subproblem_ids": [],
  "title": "Problem title",
  "abstract": "A short summary of the problem.",
  "background": "The background, definitions, and known results needed to understand the problem.",
  "references": [
    "A reference or source"
  ],
  "previous_progress": [
    "Previous progress on the problem"
  ],
  "problem_statement": "A complete, precise, and self-contained problem statement.",
  "scientific_significance": {
    "affected_field": {
      "level": "high",
      "description": "A concrete description of how this field would be affected."
    }
  },
  "solution_difficulty": [
    "One possible obstacle to solving the problem"
  ],
  "verification_contract": {
    "proof": {
      "contract": "The acceptance contract for this answer type.",
      "ci_contract": "The mechanically checkable part that can be run as CI."
    },
    "counterexample": {
      "contract": "The acceptance contract for this answer type.",
      "ci_contract": null
    }
  },
  "verification_difficulty": {
    "score": 5,
    "rationale": "The residual Agent or human Reviewer burden after mechanically checkable parts of all verification contracts have been removed."
  }
}
```

## Field semantics

- `schema_version`: the Problem Schema version.
- `problem_id`: the stable problem identifier.
- `parent_problem_id`: the direct parent problem, or `null`.
- `subproblem_ids`: the direct child problems.
- `title`: a short and unambiguous title.
- `abstract`: a short overview of the problem.
- `background`: the definitions, known results, and context needed to understand it.
- `references`: relevant literature and sources.
- `previous_progress`: progress already made on the problem.
- `problem_statement`: the complete, precise, self-contained research question.
- `scientific_significance`: affected fields, impact levels, and concrete effects.
- `solution_difficulty`: a bullet list of possible solving obstacles, without a score.
- `verification_contract`: acceptance contracts keyed by answer type. The keys replace a separate `expected_answer_type` field.
- `verification_difficulty`: one overall review-difficulty score for the whole problem.

## Scientific significance

Scientific significance has no single numeric score. Each affected field is
classified separately:

- `high`: solving the problem would directly change a core understanding,
  method, or capability in that field.
- `medium`: solving it would produce clear progress or materially advance
  several downstream efforts.
- `low`: the effect is local, indirect, or incremental.

Every entry must name the affected field and state concretely what would
change.

## Verification contracts and CI

`verification_contract` is a dictionary keyed by accepted answer type. Each
entry contains:

- `contract`: what that answer must submit, what evidence is required, and the
  conditions under which a Reviewer accepts or rejects it;
- `ci_contract`: the mechanically executable part of that contract, or `null`
  when there is no reasonable automated check.

CI means Continuous Integration: a mechanical acceptance process that runs
automatically after an answer or repository update. A `ci_contract` explains
what result the check consumes, what it checks, and what makes it pass or fail.

## Verification difficulty

`verification_difficulty` is one overall integer score from 0 to 10 for the
whole problem:

- `0`: no Agent or human judgment remains after mechanical checks are removed;
- `1–3`: a few independent, local, standard reasoning checks remain;
- `4–6`: connected derivations remain, or the Reviewer must reconstruct the
  correspondence between the problem and the answer;
- `7–9`: a long, fragile, or novel reasoning chain remains, or substantial code
  must be reviewed rather than merely executed;
- `10`: a load-bearing claim cannot be decomposed and requires holistic expert
  judgment.

The score is assigned as follows:

1. Enumerate every accepted answer type in `verification_contract`.
2. For each type, identify all parts checkable by CI, formal checkers, tests,
   substitution, finite enumeration, or another mechanical procedure.
3. Remove those parts from the review burden. They are removed even when the CI
   implementation has not yet been written, provided the mechanical procedure
   is clear.
4. Identify what an Agent or human Reviewer must still judge for every answer
   type.
5. Assess all verification contracts together and assign one overall score.
6. Use `rationale` to explain the mechanical checks, the residual judgments,
   and the final score.

Verification difficulty measures review difficulty, not solution difficulty,
and is not a publication threshold.

## Parent and child problems

When a parent problem delegates solving and verification to its child
problems, these fields may be empty:

```json
{
  "solution_difficulty": [],
  "verification_contract": null,
  "verification_difficulty": null
}
```

Each dispatched child problem supplies its own solution difficulty,
verification contracts, and verification difficulty.

## Operational boundary

`problem.json` is the source of truth in every generated problem repository.
The discovery campaign converts its evidence-backed assessment into this
contract and validates it before repository creation. The following operations
consume only the validated contract:

```bash
discovery contract validate problem.json
discovery contract render problem.json --out README.md
discovery contract review problem.json --out review.json
discovery contract rewrite problem.json --prompt "..." --out rewritten.json
discovery contract publish problem.json \
  --out-dir ./problem-repo \
  --gitlab-project group/problem-repo
```

`render` is deterministic. `review` returns `accept`, `rewrite`, or `reject`
without solving the problem. `rewrite` returns a complete contract, preserves
`problem_id`, and validates the result again. `publish` regenerates README,
creates a Git repository and the named GitLab project, and pushes `main`; its
default visibility is private.
