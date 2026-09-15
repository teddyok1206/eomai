# M03 user workflow UX status — 2026-09-15

Status time: 2026-09-15 14:26 UTC

## Outcome

The automated M03 foundation is deployed and verified. Scientific Studio supports the current
request → Workflow → review approval → Item Preview → HWPX delivery path without asking ordinary
users to manage batch identities, Artifact paths, or internal keys. The final M03 acceptance still
depends on the deferred human browser tasks and the M02 content-lead review; this record does not
claim that typography, educational quality, or total reviewer time has been approved.

## Installed boundary

- Scientific Studio source: `0405087baaee6757b9139063ef7330a8dbb38d6d`
- Wheel: `eom_web_gui-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `940c24c086c0b20712856196c3ce761c7ede95ee517f5de71a4c57626be50c5f`
- Installation: non-editable, 28-file release inventory verified
- Service after deployment: active, `NRestarts=0`, `ExecMainStatus=0`
- Public HTTPS error-correlation smoke: passed with session logout

## Existing workflow protections retained

- Product concepts and Korean state labels appear before technical identities.
- Batch identities remain absent from the corpus learning UI. Existing ID-oriented application
  functions remain available for administrator support rather than being deleted.
- Runtime/preset settings are restricted to the administrator area.
- Item Preview requests clear stale edit and HWPX targets at request start or failure and ignore a
  superseded response when the user changes Item quickly.
- Browser routes, BFF routes, Application API OpenAPI operations, Preview schema discriminators,
  renderer branches, DOM selectors, ES-module dependencies, and Korean vocabulary are closed by one
  frontend/backend alignment suite.
- HWPX build selection is revision-pinned and does not substitute an implicit latest revision.
- Browser media operations accept only an approved Item Revision and typed ordinal; Artifact paths
  and members are resolved behind the API boundary.

## Error correlation correction

The audit found that the BFF previously generated one request ID in middleware but generated a
second unrelated ID in exception handlers. The body ID therefore could not reliably locate the
request-completion log, and the browser discarded both body and header IDs.

The additive `studio-problem/1.0` JSON Schema 2020-12 contract and `StudioProblem` Pydantic model now
limit an error response to:

- a stable sanitized error code;
- a bounded generic message; and
- one server-generated `webreq_` inquiry number.

One request now carries the same ID in request state, the bounded completion log, the
`X-Request-ID` header, and the typed error body. The browser accepts the ID only when it matches the
closed shape and body/header values do not conflict. It displays the inquiry number only on an
error, while routine screens continue to hide technical IDs. The inquiry number neither retries nor
authorizes an operation; timeout recovery still follows the owning idempotency contract.

## Verification

- Web GUI source suite: 205 passed.
- Studio problem schema/model focused suite: 28 passed.
- Error, browser, and vocabulary focused suite: 36 passed.
- JSON Schema 2020-12 validation: passed.
- Strict mypy for changed Web sources: passed.
- Ruff check, format check, JavaScript syntax, route inventory, and Git diff check: passed.
- Wheel build, RECORD, source-checkout independence, installed 28-file identity, and loopback Web
  smoke: passed.
- Public HTTPS negative request: `CSRF_TOKEN_INVALID`, body/header request ID match, closed request-ID
  shape, security headers, and explicit logout all passed. No draft, Workflow, Item, Artifact, or
  HWPX build was created.

## Remaining human/product evidence

The single deferred checklist remains
`docs/status/MANUAL_ACCEPTANCE_CHECKLIST_2026-09-15.md`. M03 is not fully complete until it records:

1. actual browser navigation and rapid Item switching;
2. understandable loading, empty, denied, expired-session, and unavailable states;
3. whether content leads can identify the next action without exposing routine internal IDs;
4. the request-to-review-to-download click path and elapsed human time; and
5. changes justified by M02 reviewer evidence rather than speculative interface expansion.

Automated status: `M03_FOUNDATION=PASS`

Human/product status: `M03_USER_ACCEPTANCE=PENDING_FINAL_REVIEW`

