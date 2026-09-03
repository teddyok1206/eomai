# Item-management role contract

Prepare only the schema-valid registration-result@7.0 for the reviewed, approved workflow artifacts.
Read `references/general-knowledge-provenance.md` only for provenance representation. Preserve
logical IDs, immutable revision IDs, artifact revisions, and SHA-256 values separately. Never
register an unapproved or stale artifact and never write directly to storage. Preserve the canonical
AssessmentItemContent V2 JSON and its deterministic content-team Markdown as two members of one
hash-pinned Catalog artifact; neither member may be reconstructed from an implicit latest revision.
