# Knowledge-backed Item Preset Succession V2

Status: implemented

## Boundary and canonical source

`knowledge-grounded-item` is the Graph-backed execution policy for one-item production. Its
canonical executable role policy is the current immutable `standard-item` revision; its retrieval
policy remains the reviewed `integrated-science-textbooks` access-policy revision and bounded
Evidence Bundle budget. A successor copies those pinned role and bundle pointers into a new V2
preset revision. It never edits or resolves through a historical revision implicitly.

## Identity, access, and data structures

The logical preset ID, immutable revision ID, policy hash, bundle revision IDs, access-policy
revision ID, and hashes remain separate. Admission uses the unique indexed `preset_key` lookup and
locks that logical row. It then reads the append-only revision chain ordered by revision number.
The chain is small and succession is rare, so one bounded `O(r)` scan is simpler than a new cache;
current request resolution remains an indexed `O(1)` pointer lookup.

## Transaction, concurrency, and failure

Draft selection/creation runs under the logical-row lock. Exactly one matching draft or released
policy may be reused. An unresolved different draft, duplicate matching policy, retired logical
preset, stale base pointer, or incompatible workflow protocol fails explicitly. Evaluation evidence
pins the exact draft policy hash; release appends a new immutable revision and moves only the logical
current pointer. Replaying the same manifest is idempotent and does not add a revision or artifact.

## Dependency direction and alternatives

The operator CLI calls the existing orchestrator application service; persistence and NAS artifact
publication remain infrastructure adapters. Workers are not involved and no model is invoked. An
API fallback from `knowledge-grounded-item` to `standard-item` was rejected because it would drop
Graph retrieval provenance and silently change the requested policy. Editing the existing released
revision was rejected because it would break immutable execution history.
