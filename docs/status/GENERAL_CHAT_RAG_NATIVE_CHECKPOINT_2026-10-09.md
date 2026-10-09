# CHAT-RAG-2 native/owner/history checkpoint

As of 2026-10-09 06:01 UTC. This is repository and isolated-test evidence,
**not installed/live textbook-answer acceptance**.

## Implemented boundary

- V4 native tools reuse the existing Item search/read path and add bounded
  `retrieve_eom_knowledge`. No new LLM API, queue, DB schema or dependency.
- Seven global tool calls maximum: four Item searches, one Item read, two RAG
  retrievals. R1–R3 are exact-pinned approved analysis, not original-page quotes
  or claims of PDF/PNG visual inspection. Failed/empty reads reveal no partial
  sources and do not erase already-read context.
- Actual conversation owner/claim is checked before and after tool use. Only
  Orchestrator publishes validated immutable tool records. Workers use the same
  owner-initiated duplex connection, with no Catalog/DB/NAS capability.
- Canonical V4 requests/results/dispatch and V2 tool records use the existing
  Artifact publisher and closed registered schema families. Local handoff,
  lookup, same-request replay and recovery preserve identity without generation.
- History reads batch canonical messages/results and tool records. Exact
  context hashes deduplicate authorization. Follow-up retains its original
  Graph/policy/source even when configured policy changes; revoked evidence
  explicitly fails instead of disappearing or switching to latest.
- Successful final admission reauthorizes every resolved Item selection and RAG
  context. A source revoked after reading cannot be committed as success; a
  known failure receipt can preserve the execution evidence without exposing an
  answer or rewriting history.
- Owner/API/BFF preserve typed textbook/intake/Item source references. R cards
  display title, source class and checked location; existing S buttons still
  open exact Item revisions. A textbook is never given a fake Item route.
- Worker/owner protocol 4 is explicit opt-in with an exact released policy
  revision/hash. Unconfigured installation remains protocol 3. Initial denied
  or unavailable RAG can coexist with ordinary chat; invalid pins cannot be
  downgraded to optional access.

## Verification

One final source run: **986 PASS, 0 SKIP**. This includes all chat unit tests,
Catalog chat/RAG tests, dependency boundaries, API chat and the full Web suite.
The existing Playwright/Chromium environment enabled both real-browser Preview
visibility and local MathML tests. A pre-existing FastAPI/httpx deprecation
warning remains; no dependency was changed to suppress it.

Focused native/grounded/Item/RAG regression: **147 PASS** (overlaps the source
run; do not add the counts).

Disposable PostgreSQL chat persistence: **52 PASS**, repeated after final owner
authorization changes. The three added V4 cases check canonical/idempotent
publication, source-card projection, exact follow-up, actual-owner isolation,
revoked-source rejection and ordinary answers when initial RAG access is denied.
The guarded migration cycle reached existing head `20261008_0049`; no new
migration was introduced. Disposable DB
`/tmp/eom-api-testdb-20261009054949_61b67ee0` was removed by the manifest-validated
cleanup command. No production DB test or direct state repair occurred.

Ruff/formatter PASS; mypy **53 production modules PASS**. Both schema generators
pass `--check`; predecessor schema bytes and default V3 policy serialization
remain protected by regression tests. Invalid native tool arguments produce a
known `CODEX_PROTOCOL_INVALID` failure and close the process without a retry.

Temporary validation logs reside under private `/tmp/eom-chat-rag.bwgaz7ou`.
They are workspace materialization, not committed Artifact identities, and are
not checked into Git or posted to Slack. No model, GPU or HWPX execution occurred
in this checkpoint.

## Not yet accepted

1. Compatible installed API/Catalog/chat/Web release and reviewed rollback pins.
2. Actual service-identity Catalog/native isolation and authorization preflight.
3. Authenticated textbook answer through HTTPS, canonical R citations and cards.
4. Follow-up using the exact original evidence without another retrieval.
5. Preservation check of historical completed receipts across rollout.

The goal remains ACTIVE. Source PASS does not mean activation, textbook corpus
coverage expansion or educational quality approval. No role/policy grants,
historical backfill, source mutation or six-slot changes are authorized by this
checkpoint.
