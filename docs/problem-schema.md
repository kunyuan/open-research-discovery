# Problem Schema v1.0

This is the complete public contract for one open research problem. Discovery
records, source-search logs, orchestration state, reviewer output, rankings,
and publication metadata are separate artifacts and must not add fields here.

## JSON format

```json
{
  "schema_version": "1.0",
  "problem_id": "problem-id",
  "parent_problem_id": null,
  "subproblem_ids": [],
  "title": "Problem title",
  "abstract": "A short summary of the problem.",
  "background": "Definitions, known results, and context needed to understand the problem.",
  "references": ["A relevant reference or source"],
  "previous_progress": ["Previous progress on the problem"],
  "problem_statement": "A complete, precise, and self-contained research question.",
  "scientific_significance": {
    "affected_field": {
      "level": "high",
      "description": "What solving the problem would concretely change in this field."
    }
  },
  "solution_difficulty": ["One possible obstacle to solving the problem"],
  "verification_contract": {
    "proof": {
      "contract": "What a proof must submit and the exact acceptance boundary.",
      "ci_contract": "What CI consumes, checks, and treats as pass or fail."
    },
    "counterexample": {
      "contract": "What a counterexample must submit and the exact acceptance boundary.",
      "ci_contract": null
    }
  },
  "verification_difficulty": {
    "score": 5,
    "rationale": "Residual Agent or human review after mechanical checks are removed."
  }
}
```

The 14 top-level fields above are exhaustive. Workflow metadata and separate
answer-type or numeric scientific-significance fields are not part of it.

## Scientific significance

`scientific_significance` is a dictionary keyed by affected field. Every entry
states the concrete effect and uses one level:

- `high`: solving the problem directly changes a core understanding, method,
  or capability in that field;
- `medium`: it produces clear progress or materially advances downstream work;
- `low`: its effect is local, indirect, or incremental.

There is no overall numeric significance score.

## Verification contracts and CI

`verification_contract` is keyed by accepted answer type, such as `proof`,
`counterexample`, `exact_solution`, `experiment`, or `code`. The key replaces a
separate `expected_answer_type` field. Each entry contains only:

- `contract`: what must be submitted, what evidence is required, and the
  conditions under which a reviewer accepts or rejects it;
- `ci_contract`: the mechanically executable part, or `null` when no reasonable
  mechanical check exists.

CI means Continuous Integration: an automated check run after an answer or
repository update. A useful `ci_contract` says what artifact it consumes, what
procedure it runs, and the exact pass/fail condition. It must not hide an
unresolved scientific judgment behind words such as “verify” or “decide.”

## Verification difficulty

`verification_difficulty` is one overall integer from 0 to 10 for all accepted
answer types together:

- `0`: no Agent or human judgment remains after mechanical checks;
- `1–3`: a few independent, local, standard reasoning checks remain;
- `4–6`: connected derivations remain, or the reviewer must substantially
  reconstruct the correspondence between problem and answer;
- `7–9`: a long, fragile, or novel reasoning chain remains, or substantial code
  must be reviewed rather than merely executed;
- `10`: a load-bearing claim cannot be decomposed and requires holistic expert
  judgment.

Assign the score by enumerating every answer type, removing all parts that can
be checked by CI, formal checkers, tests, substitution, finite enumeration,
replay, or certificates, and then assessing the remaining human/Agent judgment
across all contracts. The rationale must describe both the removed mechanical
work and the residual review. This score measures verification difficulty, not
solution difficulty, and is never a publication threshold.

## Parent and child problems

When a parent delegates solving and verification to listed children, these
fields may be empty:

```json
{
  "solution_difficulty": [],
  "verification_contract": null,
  "verification_difficulty": null
}
```

Each child supplies its own complete verification contract.

## Operational boundary

`problem.json` is the source of truth. README is a deterministic projection.
The only contract operations are:

```bash
discovery contract validate problem.json
discovery contract render problem.json --out README.md
discovery contract review problem.json --out review.json
discovery contract rewrite problem.json --prompt "..." --out rewritten.json
discovery contract publish problem.json --out-dir ./problem-repo \
  --gitlab-project group/problem-repo
```

Review output and rewrite instructions remain outside `problem.json`.
