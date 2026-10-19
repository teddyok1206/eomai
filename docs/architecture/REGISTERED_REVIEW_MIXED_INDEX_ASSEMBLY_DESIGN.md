# Mixed index assembly from source-plan2

2026-10-19 UTC. Internal source-only composition of already defined plan2,
binding2/index2 and existing encoding/shard1; no new wire schema or authority.

1. Responsibility: reconstruct old/new source associations around owner-verified
   immutable numerical rows. Never copy prior source bindings into a new index.
2. Canonical inputs: current full source-plan2 and exact committed rows/shards.
   Catalog source/IAM/current accepted V2 base checks remain upstream and late.
3. Identity: source/base/review or solution/profile/encoding/row are distinct;
   actual per-branch extractor is accepted1 or registered-review1, not mixed2.
4. Resolution: validate plan2, each selected encoding/row/shard reference, exact
   predecessor identity/hash and both binding families. Previous1 or2 must have
   the same actual logical index ID; namespace2 normally begins a new index.
5. Access: bounded encoding lookup, source lookup, required-shard membership and
   deterministic pointer ordering; no query, filesystem or numerical operation.
6. Structures: tuples plus local encoding/pointer maps/sets. Extract only shared
   row/shard selectors into the existing assembly owner for two actual callers.
7. Scale: at most1,024 sources/rows/shards; O(n) lookup plus O(k log k) pointer
   ordering and existing schema/hash costs. No source-by-shard nested scan.
8. Concurrency: prepared basis belongs to one current authorized root, not an
   exported grant. Existing Artifact commit, late fences and Registry CAS remain.
9. Dependency: Catalog application assembly depends on pure workflow/Catalog
   contracts; domain contracts do not import services or infrastructure.
10. Failure: duplicate/foreign rows, missing/changed shards, wrong predecessor,
    wrong original branch/base and empty binding coverage fail closed. Partial
    available rows are honest partial coverage; missing reports have no vectors.
11. Alternative: copying old bindings retains revoked/changed sources; copying
    the entire old assembler duplicates row/shard invariants. Share those two
    pure selectors and keep separate explicit branch composition instead.

Source evidence: assembly2/old assembly/plan2/mixed contracts/dependency five
suites115 PASS /18.77s, `/tmp/registered-review-mixed-assembly-final.xml`.
Strict mypy3/Ruff3/format3 and diffcheck pass. Existing legacy binding bytes are
equal for identical plan/row inputs; one shared encoding retains both source
associations. Empty/partial coverage, revoked source, missing report, row/shard
corruption and exact predecessor identity/schema family are covered.
First RED `/tmp/registered-review-mixed-assembly.xml` (17 PASS/1 FAIL) exposed
the shared mixed-reference validator accepting a schema1 pointer for a schema2
parent value. The contract owner fixed that exact family check; the negative is
retained. No runtime, database, model, registration or activation was executed.
