# Private Chat QUERY exact static admission successor

Design before behavior, 2026-10-18 UTC. This completes one existing installed-owner
gate; it is not a new execution interface or evidence of operating activation.

1. Responsibility: the existing workflow admission map may admit exactly private
   QUERY1.0.0/private-chat-query1.0 after its complete owner/runtime composition is
   selected. Generic role/INDEX/reference execution remains a different family.
2. Canonical sources: unchanged closed1.3 definition and existing private request,
   origin, policy, Artifact, current source and native admission owners.
3. Identity: preserve the exact definition key/version/canonical SHA and original
   immutable request/turn/claim. No latest alias, new query or schema is introduced.
4. Resolution: current active DB definition/canonical hash, actual paired private
   owner/executor, live operator/source/origin and sealed native runtime still must
   independently validate. Static admission alone establishes none of those.
5. Access: one O(1) map lookup at import/submission/claim. Existing indexed exact
   definition reads and purpose-specific FIFO/lease fences are unchanged.
6. Structure: add one immutable admission tuple to the existing authoritative map;
   supply the matching closed graph in
   `config/workflows/local-embedding-private-chat-query.v1.yaml` for the existing
   public definition compiler/importer. No registry, index, queue, cache, table,
   migration or dependency.
7. Complexity: O(1) time/space addition. Current bounded source and native costs do
   not change. No payload or model bytes are copied.
8. Transaction: supported definition import creates an admitted active snapshot;
   replay does not activate an existing inactive row or repair a conflicting hash.
   Private submission/claim owns its existing clean root/current fences. Import
   the exact private definition after the old shared bootstrap; an inactive
   existing snapshot requires an independently supported deployment transition.
9. Dependency: workflow value policy stays infrastructure-free. The new private
   owner SDK needs this tuple; existing shared185 readers and CPUb010 numerical
   code do not consult it to validate an already committed private receipt.
10. Failure/retry: unsupported versions, inactive/malformed definitions, absent or
    borrowed ports, stale actor/source and uncertain original execution still
    fail closed. No retry, TTL/authentication change or runtime activation here.
11. Alternative: changing flags or patching the predicate at runtime leaves the
    real production submission/claim gate closed and bypasses its release owner.
    One reviewed static entry with positive and boundary-negative tests is the
    smallest correct successor; rebuilding unrelated operating components is not
    required solely to make their source commits match.

Verification must separate static SOURCE_PASS from actual private installation,
definition import/reconciliation, policy/config selection, live native execution
and current-operator materialized/cited consumer delivery.

The first released-static regression exposed an early type/family guard that was
conditional on non-ROLE candidates. The existing SQL ROLE predicate already
quarantines private rows, but a forged ROLE header must also fail before any DB
claim, including a ROLE header carrying a local INDEX request with INDEX ports.
Make the existing request-to-family check total: ROLE has no native request,
while private/reference requests match their exact native family. This changes
no SQL or authority rule; it
removes dependence on the previous closed static gate to mask a mismatched header.

Verification on 2026-10-18 UTC: the detached source cohort passed 280 focused
offline tests (63.30 s), strict mypy for both production files, and Ruff/format
for all 13 Python files. The parent-operated guarded PostgreSQL `embedding-tests`
purpose passed 125 tests (279.94 s), including the three real fixed-asset public
import cases. Reusing that DB for `embedding-stage-tests` produced 241 passes and
16 fixture-precondition failures (264.38 s): retained private history and its
active definition contradicted the fixture's empty-history/inactive assumptions.
That failed evidence remains in `/tmp/eom-c4-admission-db.MsAjhKqX/TESTFINAL.stdout`;
no assertion or runtime guard was relaxed and no history was cleared. The same
unchanged stage cohort passed all 257 tests (261.38 s) in the separately prepared,
migrated and reconciled fresh guarded DB state
`/tmp/eom-api-testdb-20261018134420_af3c84bc`. These separate-purpose results prove
source/persistence behavior, not operating private QUERY admission or delivery.
