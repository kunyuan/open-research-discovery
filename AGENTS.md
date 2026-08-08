# Repository contract

Work from first principles and keep the implementation minimal.

1. `schemas/problem.schema.json` is the sole public scientific data contract.
2. Final problem repositories contain `problem.json` and its deterministic `README.md` projection.
3. Search traces, workflow state, Agent output, review verdicts, rankings, and publication metadata stay outside `problem.json`.
4. Do not add a Problem Contract field without an explicit schema decision.
5. A leaf problem must be scientifically coherent and determinate: after receiving a proposed solution, a reviewer must be able to decide whether it solves the stated problem.
6. Generalization beyond a source is allowed when justified and accurately attributed. Do not weaken a target or add restrictions merely to simplify verification.
7. `verification_difficulty` rates only residual judgment after mechanical checks; it is never an admission threshold.
8. Prefer LKM for scientific discovery, supplement with web search, and audit source context before formulating a problem.
9. Run `uv run pytest -q` before committing.
