# Gaia CLI interface for LKM research

Use the installed Gaia CLI. Inspect `gaia search lkm <command> --help` when
exact flags differ by version.

## Knowledge recall

```bash
gaia search lkm knowledge "<query>" \
  --scopes claim --scopes question \
  --retrieval-mode hybrid \
  --include-paper-enrich \
  --sort-by comprehensive \
  --offset 0 --limit 100 \
  --no-hint
```

Useful variants:

- `--sort-by recent` for later work;
- `--retrieval-mode lexical` with exact theorem, method, benchmark, or formula
  aliases;
- `--paper-id` or `--doi` to constrain a known paper;
- `--reasoning-only` when only nodes attached to reasoning are useful;
- `--keywords` to add required terminology.

Search both claim and question scopes for later-literature research. These
question hits are retrieval evidence only and are never source open-question
records.

## Reasoning and exact retrieval

```bash
gaia search lkm reasoning "<query>" --max-chains 20 --sort-by comprehensive
gaia search lkm reasoning --claim-id "<claim-id>" --max-chains 20
gaia search lkm nodes "<node-id>"
gaia search lkm package --doi "<doi>"
```

Use `reasoning` to inspect how claims are supported or connected, `nodes` to
retrieve known IDs, and `package` for a known paper graph. The deterministic
discovery pipeline still uses the direct `papers/graph` API, not `package`, for
strict extraction of `data.papers[].open_questions`.

## Operational interpretation

Gaia LKM commands use these exit-code classes:

- `0`: success;
- `1`: business/API failure;
- `2`: transport failure;
- `3`: missing access key;
- `4`: invalid arguments.

Preserve the command, version, query, filters, timestamp, output, and exit code
in campaign evidence. Avoid `--out` inside a read-only headless-agent sandbox;
capture stdout through the pipeline instead.
