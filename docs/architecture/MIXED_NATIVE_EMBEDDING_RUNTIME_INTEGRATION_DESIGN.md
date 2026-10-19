# Mixed native embedding runtime integration

## Boundary and canonical source

The existing Orchestrator encoding reservation owner, Catalog Artifact resolver and
runner executor remain the only runtime path. Source-plan2 carries accepted solution
or registered independent-review evidence. Its numeric encoding request, encoding Job,
input, result, shard and vector row remain version1: evidence kind does not change the
numeric operation. Ownership2 records and completion2 identify the new metadata family.

Logical Workflow, launch Job, computational Job and Artifact identities remain distinct.
Every reproducible reference pins its revision, schema and raw/semantic hash. Catalog
resolves current permissions and source proof before materialization; the same root
fences mutation immediately before commit. An old completed encoding may be borrowed
by a new launch, but its original owner1 intent/completion is never retagged as2.

## Access, structure and concurrency

Dominant access is indexed encoding-key claim, bounded ordered event history, keyed
row reuse and immutable manifest assembly. Keep the existing unique Job key, ordered
locks, bounded PostgreSQL retry/savepoint, four-phase coordinator and registry CAS.
There is no new queue, database table, worker protocol or scheduler. Per-batch maps and
sets provide O(n) metadata processing; shared Artifact groups are read once, not per row.
Batch and row bounds remain the released limits. No binary is stored in PostgreSQL.

Explicit supported-family dispatch is owned by workflow contracts. Old parsers remain
strict. Runner and infrastructure adapters consume those public functions; contracts
never import adapters. Publication uses the same Orchestrator file-set owner. Local
staging is only the existing explicit input/validation/commit materialization boundary.

## Failure, replay and alternative

Missing, stale, wrong-family, hash or current-authorization failure is explicit. An
uncertain launch is read/reconciled through its original identity, never resubmitted
with a new key. Recovery reuses committed allocation/checkpoints. A family mismatch
cannot be repaired by rewriting historical rows or substituting latest.

The simpler alternative, widening version1 schemas or serializing2 as1, is insufficient:
it changes released meaning and loses the accepted evidence provenance. A second
executor/reservation state machine would duplicate ownership and is not introduced.
Tests cover old bytes, strict family rejection, original-owner reuse, replay,
concurrent claim, bounded reads and real disposable PostgreSQL transitions.
