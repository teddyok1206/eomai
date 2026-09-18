# ADR 0098: Item-production solution-evidence requirement

## Context

`generic-item-development@1.11.0` requires an Evidence Bundle V5 whose selected past-exam
evidence pins an accepted additive solution report. The private API-to-Catalog item-production
command previously had no field that could express that requirement, and the Catalog adapter
always disabled solution-evidence resolution. The execution resolver therefore rejected the
otherwise compatible workflow/role/pack successor before a workflow transaction committed.

## Decision

Add immutable Catalog application request schema V16. It extends the existing bounded
item-production request with a required `solution_evidence_requirement` enum:

- `NONE` preserves the existing V2--V4 evidence behavior;
- `REQUIRE_ACCEPTED_SOLUTION_REPORT` performs the existing indexed, set-based successor lookup and
  fails before artifact publication if no selected candidate resolves an accepted solution report.

The API derives the value from the admitted workflow definition: only workflow `1.11.0` requests
the required mode. The value participates in the command submission hash. Same-key replay must
also prove that a required request resolves a V5 publication; it never substitutes a newer bundle.

The canonical source remains the active Graph snapshot plus immutable accepted analysis and
solution-report revisions. PostgreSQL stores only bounded pointers and hashes; report bytes remain
canonical artifacts. Candidate lookup and solution merge remain O(candidates + accepted
successors), using the existing indexed predecessor relation and in-memory map.

The API owns workflow-to-requirement selection, Catalog owns evidence resolution and artifact
publication, and the Orchestrator continues to validate the returned pinned plan. There is no new
queue, database schema, worker communication, or NAS writer.

## Failure, retry, and rollback

Missing or invalid required solution evidence fails closed before evidence artifact publication.
API idempotency and Catalog's derived key continue to serialize retries; a required-mode replay of
a non-V5 historical result is rejected. Rollback selects the previous workflow/pack/preset for new
requests; immutable requests, evidence, and failures are retained.

## Rejected alternative

Inferring V5 from the currently active Pack inside Catalog would couple Catalog to workflow
activation state and make replay non-reproducible. Always enabling solution evidence would silently
change historical workflows. The explicit typed enum is the smallest reproducible boundary.
