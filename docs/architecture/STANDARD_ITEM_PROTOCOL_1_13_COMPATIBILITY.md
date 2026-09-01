# Standard-item protocol 1.13 compatibility

Status: implemented source design

## Responsibility and boundary

`standard-item` owns the immutable worker execution policy selected by a one-item workflow. Workflow
definition `generic-item-development@1.6.0` emits the V6 role-result family and therefore requires
`workflow-role/1.13.0`. Content Pack `generated-knowledge-item@1.5.0` and the preset must be deployed
as one compatible creation-time set before a V6 request is accepted.

## Canonical identity and pointers

The logical preset remains `standard-item`. V4 creates a new immutable Execution Preset Revision;
it does not edit V3. A workflow resolves the logical key once, validates the released Revision,
protocol compatibility, capacity policy, role policies, instruction/reference bundle revisions and
hashes, then pins the resolved plan. Historical plans continue to point to their original Revision.

## Access patterns and structures

The dominant operation is indexed lookup by `preset_key`, followed by primary-key lookup of its
current Revision and a four-entry role-policy map. Existing unique keys, foreign keys and indexed
relations are retained. Resolution is O(1) for the logical/current Revision and O(r) for four roles;
space is O(r) in the immutable plan. No cache or duplicated binary payload is introduced.

## Transaction, failure and rollout

Preset publication is transactional and idempotent for the reviewed immutable content. Workflow
creation fails closed before worker execution when the active Revision is absent, stale, unhashed,
unreleased, or protocol-incompatible. Deployment order is:

V4 uses a new bootstrap timestamp for its new instruction bundles and preset Revision. Reused
role-guidance bundle IDs instead use the guidance contract's fixed original timestamp, so their
stable IDs and canonical bytes remain identical across later compatible preset publications.

1. install code and the V4 JSON Schema;
2. bootstrap and release `standard-item` V4 from the reviewed source commit;
3. verify the current Revision pins `workflow-role/1.13.0` and exact bundle hashes;
4. only then accept a new `generic-item-development@1.6.0` request.

Rollback moves only the mutable current-Revision pointer to the preserved V3 Revision and does not
rewrite workflows or artifacts. Reusing V3 was insufficient because its immutable compatibility
contract intentionally permits only `workflow-role/1.12.0`; weakening validation would allow a
worker to receive an unrecognized result protocol.
