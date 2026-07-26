# Problem-Solving Agent Contract

1. Read `problem.yaml`, especially `resolution_audit.surviving_open_core` and
   `resolution_audit.progress_assessment`.
2. Read the annotated bibliography and current baseline before searching.
3. Run `make check` before changing code or data.
4. Work on a dedicated branch. Use pull requests as attempt boundaries.
5. Put the candidate artifact in `submission/` using the declared format.
6. Run `make verify` and preserve verifier output in the pull request.
7. Distinguish a valid candidate, an improved bound, a complete solution, and
   a novel solution. The local verifier proves only the first two when encoded.
8. Refresh the later-resolution audit before claiming a new result. If major
   progress is found, reassess the remaining problem's importance and
   verification profile before continuing.
9. Record failed approaches that materially constrain the remaining search.
10. Do not weaken the verifier or success condition to make a candidate pass.
