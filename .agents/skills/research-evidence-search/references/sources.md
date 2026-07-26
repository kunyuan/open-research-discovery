# Evidence sources and content levels

Choose sources by the evidence needed, not by a global precedence rule.

## Bohrium LKM

LKM can provide paper metadata and abstracts, compressed conclusion claims,
and reasoning chains extracted from papers. These representations are useful
for broad recall, claim-level navigation, alias discovery, and reconstructing
connections across papers.

Label LKM material accurately:

- bibliographic records: `metadata`;
- an abstract: `abstract`;
- a compressed conclusion or claim node: `compressed_claim`;
- a structured chain connecting claims or reasoning steps: `reasoning_chain`.

Compressed claims and reasoning chains can omit qualifications, assumptions,
notation, negative results, or scope. Inspect an accessible original source
when one of those details is load-bearing.

## Web-accessible sources

Web search can find publisher and repository metadata, DOI landing pages,
abstracts, preprints, author manuscripts, supplementary material, citation
trails, and terminology aliases. Depending on what was actually inspected,
label the evidence `metadata`, `abstract`, `partial_full_text`, or `full_text`.

Do not upgrade a snippet to an abstract or an abstract to full text. Record
access limitations.

## Combining sources

Useful routes include:

- LKM query -> paper identifiers -> accessible original text;
- web query -> DOI/title -> LKM claim and reasoning retrieval;
- known paper -> LKM neighbors/citations -> web verification;
- ambiguous LKM compression -> original abstract/text -> refined LKM query.

Agreement between independent representations increases coverage, but it does
not turn retrieval rank into scientific confidence. Base conclusions on the
specific supported statements.
