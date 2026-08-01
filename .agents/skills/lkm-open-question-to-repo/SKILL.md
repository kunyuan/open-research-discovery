---
name: lkm-open-question-to-repo
description: Compatibility entry point for older LKM-only campaigns. New topic campaigns should use multi-source-open-problem-to-repo.
---

# LKM Open Question to Repo — Compatibility

For schema-v1 campaigns, preserve the original strict ingestion boundary:
candidate papers are queried through the direct LKM paper-graph endpoint and
only `data.papers[].open_questions` creates source questions.

For new work, use `$multi-source-open-problem-to-repo`. It retains the strict
LKM route while adding context-grounded LKM/web/book/reference discovery,
verification-first decomposition, scientific-significance scoring, and one
repository per topic. Do not use this compatibility skill to reintroduce a
verification-difficulty publication threshold.
