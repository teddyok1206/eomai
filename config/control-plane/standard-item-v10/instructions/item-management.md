# Item-management role contract

Prepare registration-result@9.0 only for the exact approved workflow artifacts. Preserve logical
IDs, immutable revision IDs, artifact revisions, and SHA-256 values separately. Keep canonical
AssessmentItemContent V3 JSON and deterministic content-team Markdown V2 as members of one pinned
Catalog artifact. Bind exactly the ordered immutable PNG Artifact Revision pointers for IMAGE slots
and none for absent slots. Never resolve an implicit latest value or write directly to storage.
