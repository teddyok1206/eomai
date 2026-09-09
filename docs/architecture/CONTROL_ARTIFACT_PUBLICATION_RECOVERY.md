# Control Artifact Publication Recovery

Status: implementation design for the existing `ControlArtifactPublisher` boundary.

1. **Responsibility and boundary.** The Orchestrator remains the sole owner of validating and
   committing bounded control Artifact bytes to NAS. This change extends that existing use case;
   it does not create another publisher or let a Catalog service write storage directly.
2. **Canonical source.** The caller supplies one already validated immutable byte string plus its
   member contract. The persisted Job request is the recovery authority after the first database
   commit. A replay never substitutes another payload or an implicit current revision.
3. **Identity and revision model.** Job ID, logical Artifact ID, Artifact Revision ID, member
   SHA-256, file-set manifest SHA-256, protocol version, and source release commit remain separate.
   The first committed Job owns the three generated IDs; every replay reuses them. New publications
   use `control-artifact/1.1`, whose persisted request adds the first attempt's exact UTC manifest
   timestamp needed for deterministic recovery. Replay uses that persisted timestamp rather than a
   caller's later wall clock. Successful `1.0` publications remain readable, but their
   nonterminal Jobs cannot be resumed because that timestamp was not persisted.
4. **Pointers and resolution.** Replays validate the Job request hash and exact member name,
   schema, media type, Artifact type, byte count, and content hash. Successful replay additionally
   validates the approved Job/Artifact/ArtifactRevision triple and its single-member manifest.
   Missing, terminal, or drifted state fails explicitly.
5. **Access patterns.** Publication is keyed by the unique indexed `jobs.idempotency_key`. Job,
   Artifact, and ArtifactRevision resolution uses their existing unique or primary-key indexes.
   State advancement is ordered lookup in a six-entry module-owned transition map.
6. **Data structures and indexes.** A request dict is compared once and each state advances through
   one lookup in the fixed transition map, so CPU and memory are O(1) for the bounded single member.
   The existing unique
   idempotency key and one-to-one Job/Artifact indexes are sufficient; no migration is required.
7. **Scale and complexity.** Payloads remain capped at 2 MiB. One PostgreSQL session advisory lock
   is held per idempotency key while the bounded publication runs. A digest collision can only
   serialize unrelated publications; it cannot alias their unique database keys.
8. **Transaction and concurrency.** Production PostgreSQL callers acquire the same session-level
   advisory lock before Job lookup and retain it through NAS and database completion. Non-production
   dialects use one process-local lock for deterministic tests. Database transitions remain short
   transactions; NAS I/O is not performed while a row transaction is open.
9. **Dependency direction.** The application/infrastructure publisher depends on identifiers,
   protocol/state-machine rules, repository functions, and the NAS adapter already owned by the
   Orchestrator. Contracts and domain models gain no infrastructure dependency.
10. **Failure, retry, and idempotency.** A crash or recoverable exception leaves CREATED through
    COMMITTING nonterminal. Replay re-stages the same bytes, advances only the missing legal states,
    and uses the idempotent NAS commit to reconcile NAS-before-database loss. SUCCEEDED returns the
    same pointer. FAILED/CANCELLED and any hash or request drift are terminal explicit errors.
11. **Simpler alternative.** Returning `INCOMPLETE` for every non-SUCCEEDED replay is smaller but
    permanently strands a semantic idempotency key after ordinary process loss. A new publication
    framework would duplicate the existing Artifact boundary. State-aware continuation inside the
    current publisher is the smallest implementation that preserves its ownership and contracts.

Required tests cover CREATED replay, each resumable state, NAS-before-database recovery,
SUCCEEDED replay, terminal rejection, request drift, concurrent same-key exact-one creation, and
approved pointer/manifest drift.
