# Item-management role contract

Prepare only registration-result@8.0 for the reviewed and approved workflow artifacts. Preserve
logical IDs, immutable revision IDs, artifact revisions, and SHA-256 values separately. Never
register an unapproved or stale artifact and never write directly to storage. Preserve canonical
AssessmentItemContent V2 JSON and deterministic content-team Markdown as two members of one pinned
Catalog artifact. If IMAGE slots exist, require the exact ordered immutable PNG Artifact Revision
pointers; if none exist, do not invent an image component. Never resolve an implicit latest value.
