# Application API release source identity

## Decision

1. **Responsibility and boundary.** The Application API wheel carries a small, immutable build-info
   document that identifies the exact source snapshot used to build the three-wheel release. It is
   release evidence, not a runtime Git-discovery mechanism.
2. **Canonical source.** A clean, fixed Git commit is canonical. The release builder derives its
   root tree ID and deterministic `git archive --format=tar` SHA-256 directly from that commit.
3. **Identity and revision model.** `source_commit`, `source_tree`, and
   `source_archive_sha256` are separate immutable identities. Package version and UTC build time are
   descriptive values and never replace any source identity.
4. **Pointers and resolution checks.** The embedded document pins all three source identities. The
   loader accepts only canonical JSON matching the Draft 2020-12 schema and the frozen Pydantic
   model. Missing resources, duplicate keys, unknown fields, non-UTC timestamps, and malformed or
   uppercase hashes fail closed.
5. **Access patterns.** Release construction performs one commit lookup, one tree lookup, one
   sequential archive write/hash/extract, and one build-info lookup. Runtime consumers perform a
   bounded keyed resource lookup and a single parse.
6. **Data structures and indexes.** A frozen typed value object is sufficient; the document has no
   independent mutable lifecycle and needs no database table or index. Canonical object keys make
   byte comparison deterministic.
7. **Scale and complexity.** Build-info is bounded to 4 KiB and validates in O(1) space for its fixed
   field count. Archive materialization is O(source bytes) time and space, once per release; hashing
   streams bounded chunks rather than duplicating the archive in memory. Wheel RECORD verification
   is O(total wheel bytes) and uses a map for exact member-path membership and deduplication.
8. **Transaction and concurrency boundary.** The selected commit cannot change during a build. The
   archive is an immutable snapshot, so later working-tree activity cannot alter wheel inputs. Wheel
   inspection recomputes the archive hash before installation. After broad inspection, a stable-FD
   scan captures each wheel's raw SHA-256 and filesystem identity; the exact set is compared again
   immediately before and after `pip`. Tracked symlinks and unmaterialized submodules are rejected
   because they would make the snapshot dereference another source boundary.
9. **Dependency direction.** The schema and Pydantic DTO live in API contracts. The Application API
   resource loader depends on that contract. Git, tar, hashing, and wheel inspection remain in the
   release infrastructure script; contracts never import them.
10. **Failure, retry, and idempotency.** Any source identity, schema, packaged-resource, wheel
    RECORD member digest/size/path-set, or installed-wheel mismatch aborts. The RECORD verifier runs
    before and after the broader wheel inspection and again on the exact `pip` arguments immediately
    before installation; the installed typed build resource is then compared with the selected
    commit/tree/archive. Rebuilding the same commit reuses those source identities; build time and
    wheel hash may differ without changing source identity. The pre-existing deployment JSON remains
    a human rollback note, not machine-verifiable provenance and not an input to completion evidence.
11. **Simpler alternative rejected.** Recording only `git rev-parse HEAD` is insufficient: it does
    not bind the root tree or the exact archive bytes supplied to the build and permits a wheel to
    claim a commit while being assembled from mutable working-tree bytes.

Git, GNU tar, and SHA-256 coreutils are existing release-host tools, not new application runtime
dependencies. The Application API declares its already-deployed `jsonschema` library directly
because the resource loader now owns Draft 2020-12 validation rather than relying on a transitive
dependency. Runtime code does not consult Git, environment variables, repository paths, or the
network for release identity.
