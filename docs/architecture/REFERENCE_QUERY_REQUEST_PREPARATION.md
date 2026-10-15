# Reference QUERY request preparation

2026-10-15 UTC. Scope: source application composition, not a new active API or
native service. The installed independent canary and its pending authentication
are not changed by this work.

1. **Responsibility/boundary:** a Workflow application function constructs the
   production QUERY request from an already pinned approved-reference context and
   trusted owner controls, then invokes existing atomic Workflow/START admission.
   API/CLI must not recreate operator audit, policy or queue rules independently.
2. **Canonical source:** existing context/source/Graph/policy pins, committed
   native policy/bundle Artifacts, exact Workflow definition and original stored
   request. No new authority, search engine or preparation registry.
3. **Identity/revision:** preserve context logical ID/hash, actor identity, pinned
   control/definition revisions and original Workflow/command/idempotency key.
   Current permission fingerprint is recorded only on first creation; replay
   preserves the original audit while rechecking actual current authority.
4. **Pointers:** reuse configured control/member schema/media/lifecycle/canonical
   bytes/hash checks and existing full QUERY/source/native admission. Factor the
   existing bounded control reader, not a second reader. It reads control bytes
   only and does not grant source permission or model execution.
5. **Access patterns:** exact unique idempotency lookup; exact definition key and
   version lookup; bounded control-member materialization; official source owner.
6. **Structures/indexes:** existing Workflow unique key and definition key/version
   constraint, frozen contracts and canonical hashes. No table/index/migration.
7. **Complexity:** O(1) indexed metadata lookups plus bounded policy/bundle IO and
   existing anchor/index admission. No population scan, vector encoding or new
   large DB payload. Query input text remains local to the native owner.
8. **Transactions/concurrency:** require the actual owner's active, nonnested root;
   do not open/commit another root. Existing atomic admission/unique conflict and
   complete-root rollback remain the only persistence implementation.
9. **Dependencies:** application uses existing Catalog verifier and pinned-reader
   public interfaces; source control IO stays in its current infrastructure
   module. Domain/contracts gain no SQL, files, HTTP or ML dependencies.
10. **Failure/replay:** authorize before metadata disclosure. Same key must retain
    exact actor/context/control/definition request. Replay reads the original
    request before building any new audit/control selection. Changed scope,
    revoked authority, missing definition or corrupt controls fail explicitly;
    no latest, new key, model retry or partial-success rewrite.
11. **Simpler alternative:** a thin wrapper around the existing full request would
    leave duplicated canary/CLI request construction and audit drift. This function
    owns that concrete construction but reuses existing admission/persistence.
    A new queue, generic service layer or registry would be unnecessary.

Protocol-first: serialized inputs and outputs remain the existing closed Draft
2020-12 SimilarityContextRequest and ReferenceQueryWorkflowRequest1.0; both parse
before use. The new internal application function has typed arguments and returns
the existing ReferenceQueryWorkflowSubmitted value. There is no new wire message
or worker behavior, so no speculative schema/version is created.

Initial owner-local source/report/view-index selection is now composed through the
[initial context capture application](REFERENCE_QUERY_INITIAL_CONTEXT_CAPTURE.md),
which also reuses the original stored request on replay. This still does not
select pins from an ordinary public Item HTTP request, expose a native socket,
transfer the real API capture, run a native query,
or automatically connect HTTP item start. Those are still required next boundaries;
an actor projection cannot substitute for the real request capture. The current
repository API implementation already keeps one genuine Identity capture for workflow_start, and the
installed-provider Unix transport can import it only from the actual observed API
peer. Preserve those owners instead of storing a password/token or minting a DTO.
This source observation does not establish activation in the installed API75fdc265.

Required proof: original request/hash parity, actual canonical control bytes,
early/late authority denial, missing/corrupt controls/definition, raw shape errors,
same-key replay without rebuilding audit or changing pins, changed actor/context
denial, original atomic rollback/concurrency and model-free disposable PostgreSQL.
Source tests with synthetic IAM/transport are not actual-user/live acceptance.

## Verified source checkpoint — 2026-10-15 UTC

- Focused preparation/read-owner tests: 21 PASS. Broader affected regression:
  273 PASS in 205.57s; the focused tests overlap and are not additive.
- Guarded disposable PostgreSQL0055: 87 PASS in 65.89s. This includes actual
  Workflow/START persistence, exact replay, late denial/root rollback and two
  concurrent preparations producing one original Workflow/command. IAM and native
  execution are explicit synthetic seams; no production database or model runs.
- The initial PostgreSQL invocation had 82 PASS/4 fixture setup errors because
  the temporary Artifact root was absent. The fixture now creates that root and
  gives each independent control publication a distinct immutable test identity.
  No production check was weakened. Both failed and final logs are preserved.
- Strict mypy: two production modules PASS; Ruff/format: five Python files PASS.
  Final disposable inspection: head0055, read-only, no other connections.

The installed independent QUERY uses the previously pinned owner517e4551, not
this new preparer. Its genuine login/submission succeeded, then staging stopped
because the fixed QUERY owner directory was missing. This source checkpoint is
not its runtime recovery, model acceptance or ordinary HTTP activation.

Candidate `9fb4ace6b32d23a3e21a59142c603a2ae8c199e8`: complete API/platform/contracts
wheel build and RECORD inspection PASS. Isolated owner-pair imports and seven
production-member byte comparisons against that exact source archive PASS; checkout,
installed-prefix and numerical-import fallbacks are denied. The new preparer is
included and the existing atomic execution boundary is preserved. This candidate
uses the main11-member Identity family; the installed canary remains on its
separately verified9-member compatible owner, so these are not a mixed release set.

Build evidence:
`/tmp/eom-api-build/9fb4ace6b32d23a3e21a59142c603a2ae8c199e8.tWYCJP/dist`;
`query-request-preparation-release-build.log` and
`query-request-preparation-owner-pair.log` under the existing sanitized checkpoint
directory `/tmp/eom-identity-provider-install.nAaycoDM`.
