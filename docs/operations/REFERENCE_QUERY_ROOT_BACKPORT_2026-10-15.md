# Bounded QUERY owner correction

This maintenance release is based on the actually installed owner
`5018ad2df4d4f882b2d843876fedf38190e4db43`. It backports the two production-file
QUERY submission correction from main `2941723d`, plus its focused tests.
The implementation/design record is main's
`docs/architecture/SYSTEM_RAG_SIMILARITY_CONTEXT_IMPLEMENTATION_BOUNDARY.md`, section35.

Current Catalog/source checks run in the actual caller root before/after row
persistence, never inside SQL savepoints. A post-admission error rolls back the
whole submission root; do not mix unrelated application writes into that root.
Immutable history, request/schema bytes, idempotency and concurrent uniqueness
are unchanged. No new queue, schema, migration, grant or dependency is added.

Focused source tests194 /54.60s, Ruff/format and strict mypy on both production
modules pass on this base. Main's corresponding regression222, legacy/dependency41
and guarded PostgreSQL78 are separately recorded, not added to this release's194.
The changed QUERY code must match main; unrelated provider/role-RPC changes are
not pulled into the installed owner. Install as a new immutable inactive prefix,
preserving API75fdc265, the old owner and all numerical runtime/configuration pins.
Only a later explicit bounded canary selects this owner; normal services are not
restarted or activated by an inactive-prefix install.
