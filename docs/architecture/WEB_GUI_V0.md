# EOM Web GUI V0 architecture

## Responsibility and boundary

EOM Scientific Studio is a browser-facing BFF and static web application. It authenticates an
operator against the loopback Application API, keeps API tokens in a server-side session, and
renders sanitized Application API and Observability projections. The browser never connects to
PostgreSQL, NAS, Application API, Observability, Kordoc, or secret files directly.

The existing process on `0.0.0.0:8000` is an unrelated manual `uvicorn` process rooted at
`/home/eom/linux_server_bundle`. It is preserved. Web GUI V0 uses `127.0.0.1:8790` during
development and deployment preparation.

## Canonical source and pointers

Application API resources remain canonical. The GUI retains only an opaque server-side session,
short-lived Request Drafts, and idempotency replay results. Workflow, Item, Item Revision, Content
Pack Release, Artifact, and HWPX identities remain separate typed references. A preview pins an
Item Revision; it never resolves an implicit latest revision.

Current Application API V1 exposes Item component pointers but not component bytes. The GUI
therefore renders an A4 metadata-only state until a reviewed Application API preview endpoint is
available. It does not read NAS or dereference an Artifact path itself.

Kordoc is isolated behind the deployed chain `Application API -> HWPX Manager -> Renderer Adapter`.
Web GUI V0 has no Kordoc import, CLI, npm, workspace, or filesystem dependency. If that capability
is unavailable, the UI reports the closed capability state and never creates a fake HWPX.

The deployed HWPX delivery view can recover an existing build by its validated opaque Build ID.
The selected ID is reflected in the page query string so a refresh re-resolves the same immutable
resource through the authenticated BFF; browser local/session storage is not used. ADMIN operators
may choose from a bounded 20-row recent-build projection supplied by the existing read-only DB
Explorer boundary and optionally filter it by exact Item Revision ID. Other roles retain exact-ID
lookup without gaining build-enumeration permission. A successful build exposes a download link
only after the Application API reports `SUCCEEDED`, validation `PASS`, and a complete immutable
output pointer.

## Request Draft protocol

`schemas/web-gui/request-draft-v1.schema.json` and `request-draft-v2.schema.json` remain immutable
historical Request Draft wire contracts. New drafts use `request-draft-v3.schema.json`. V3 carries
bounded NFC-normalized authoring guidance and its SHA-256, a server-resolved Integrated Science
editorial scope, and a composite `draft_spec_sha256` over the complete reviewed request. The
browser submits only a reviewed editorial unit key; it cannot manufacture a breadcrumb or Graph
root. The Application API resolves that key through the source-controlled outline contract before
constructing the internal workflow command. Scientific Studio proxies the authenticated read-only
outline projection and does not acquire Catalog or database dependencies.

The visible hierarchy is `대단원 -> 중단원 -> 소단원`. A middle unit may be selected first and
deterministically fills its large-unit parent. A future small-unit selection will fill both parents,
but V3 deliberately exposes a disabled placeholder until a reviewed small-unit vocabulary exists.
An editorial selection may be recorded without Graph grounding. Enabling grounding requires a
selection and uses the deepest selected unit's mapped stable key; Graph revision, traversal,
policies, and storage paths remain server-owned. Natural-language guidance is treated as explicit
reviewed data and remains delimited from system instructions.

Outline V1 marks its Graph mapping as reserved candidates rather than publication proof. The BFF
therefore projects `graph_grounding_available=false`, and the Studio keeps the grounding control
disabled with a visible “Graph 매핑 준비 중” state. Editors may still classify a standard item by
대단원/중단원. A later published mapping requires an explicit successor capability contract; the
browser never infers readiness from the presence of candidate keys.

The accepted Application API currently supports `PLACEHOLDER_REQUEST`. V0 labels this path
`Generic Demo Mode` and maps a reviewed draft to the existing `generic-item-development` workflow.
The draft is not presented as an Integrated Science curriculum contract or a raw model prompt.

Catalog-backed workflow creation pins one immutable Content Intake batch. The BFF reads at most 100
`ACCEPTED` intake summaries through the authenticated Application API and requires the operator to
select one; it never silently resolves a latest intake. The selected `intake_batch_id` is stored in
the short-lived draft and submitted as a typed pointer. Application API validation rejects a pack
request without a valid intake pointer with HTTP 422 before command execution, while the catalog
service remains authoritative for existence and accepted lifecycle state. The list is bounded and
rendered with `textContent`; the browser receives no artifact bytes or storage paths.

## Access patterns and data structures

- session and draft lookup: bounded dictionaries keyed by cryptographically random IDs, expected
  O(1) lookup;
- curriculum hierarchy: one ordered immutable outline plus a key-indexed map, O(1) parent lookup
  and O(depth) reconciliation where the reviewed depth is at most four;
- idempotent replay: dictionary keyed by `(draft ID, idempotency key)`, O(1) membership;
- timeline: ordered immutable tuple, sorted once by timestamp, O(n log n) for at most 500 events;
- DB Explorer: closed entity-to-route mapping, O(1) dispatch, with API cursor pagination;
- HWPX recovery: O(1) exact Build ID lookup; ADMIN recent history is a bounded 20-row list whose
  optional Revision filter is O(n) with `n <= 20`;
- status semantics: closed lookup tables for label, icon, and tone rather than nested conditionals.

The session store is deliberately process-local for V0 and requires one service worker. A durable
store is a later scaling concern, not a hidden dependency.

## Transactions, concurrency, failure, and retry

The BFF owns no production database transaction. Application API commands retain their existing
transaction and RBAC boundary. Browser mutations require a session CSRF token. Workflow creation
and approval carry a stable idempotency key; approval also carries the resource ETag. A refresh-token
exchange may be attempted once after an expired access token, while the original idempotency key is
preserved. Other failures return sanitized stable codes and are not retried automatically.

SSE is a read-only projection stream. Reconnect uses `Last-Event-ID`; clients fall back to bounded
polling. Raw shell output, prompt bodies, generated worker bodies, credentials, and chain-of-thought
are never timeline fields.

## Dependency direction

Static interfaces and FastAPI routes call application services. Application services depend on
typed gateway protocols and web contracts. HTTP clients implement those gateway protocols. No
domain package imports the GUI or HTTP infrastructure. The GUI does not import Kordoc internals.

## Security

Access and refresh tokens are server-side only. The browser receives an opaque HttpOnly,
SameSite=Strict cookie and a per-session CSRF token. CSP uses local assets only. User and upstream
text is inserted with `textContent`, not `innerHTML`. Explorer routes and sort keys are allowlisted;
there is no raw SQL or arbitrary query language. Download identities and suggested filenames are
strictly validated, and symlink/path handling remains the Application API/HWPX Manager's concern.

## Simpler alternative considered

Letting the browser call both loopback services would require exposing ports and tokens and would
break the service boundary. Extending the Observability console into a mutable product UI would mix
read-only operational credentials with Application API commands. The narrow BFF is the smallest
design that preserves authentication, RBAC, CSRF, and future HWPX adapter boundaries.
