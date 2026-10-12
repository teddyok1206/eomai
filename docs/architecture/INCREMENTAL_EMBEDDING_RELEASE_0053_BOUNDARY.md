# Native embedding stage: exact 0053 release boundary

2026-10-12 UTC. SOURCE_ONLY; no production migration, role change or activation.
This accompanies the reviewed native Runner boundary and preserves historical releases.

1. Responsibility: existing Alembic owns stage/step constraints; the existing root release
   operator alone admits an exact migration target. No second migrator or arbitrary command.
2. Canonical source: frozen0053 DDL and the accepted release's source/wheel/archive pins.
   A version string or a parsed context does not admit installed code or DB authority.
3. Identity: assign `20261012_0053`, predecessor `20261012_0052`. Keep context1.0/0051 and
   context1.1/0052 bytes, callback targets and receipts immutable; add context/admission1.2.
4. Pointers:1.2 pins exact0053 plus existing source commit/tree/archive/snapshot/runtime/wheels.
   Reuse protected context/tree/RECORD checks; reject unknown schema, `head`, callback mismatch,
   copied cross-version context/receipt or a different installed authoritative migration head.
5. Access: one exact schema-version lookup, one exact callback→target/predecessor lookup,
   bounded metadata reads and owner preflight; no corpus/Artifact scan for release admission.
6. Structures: extend closed immutable callback tuples and schema variants.0053 keeps existing
   tables/indexes/queues; only stage CHECK and total-boolean native-step CHECKs change.
7. Scale: O(context + admitted release members) at admission; existing bounded callback/DB
   timeouts. No package bytes, model vectors, credentials or item content in new DB values.
8. Transaction: Alembic's existing transaction owns DDL. Verify accepts only exact0053;
   upgrade accepts only0052→0053 or exact0053 replay, with actual schema-owner checks. No
   transaction spans model execution. Downgrade refuses any native history before narrowing.
9. Dependencies: schema before behavior; no new dependency. Shell admits root interpreter and
   immutable source, then invokes the existing supported operator callback. Domain imports none.
10. Failure/retry: target/build/owner/head mismatch denies before upgrade. Unknown timed-out
    migration outcome requires actual head inspection, not blind resubmission. Retain receipts;
    no old context rewrite or dynamic latest fallback. Source head changes only with0053 present.
11. Simpler alternative: editing0052 or routing its callback to latest rewrites released meaning.
    One additive schema/callback pair is sufficient; no generic migration or release framework.

Tests retain1.0/1.1 byte pins and exact behavior, cover1.2 closed fields/raw pin/context/receipt
association, wrong callbacks/targets/head/owner,0052 predecessor and idempotent0053 replay.
Existing deploy verification adopts the exact new callback and source head together. Its prior
assertions about the *current* deployment are updated, not its historical callback expectations.
Actual0053 upgrade/down/up/constraint/downgrade-refusal gates run only in the existing disposable
DB harness. These tests never authorize production migration or native runtime/model/GPU work.

The existing guarded `testdb_run.sh` has one closed `embedding-stage-tests` purpose. It uses the
same owner URL/manifest/marker preflight and the official stage-owner fixture, not a new credential
or profile. It selects only the18 prepared integration cases; production DB tests remain forbidden.
