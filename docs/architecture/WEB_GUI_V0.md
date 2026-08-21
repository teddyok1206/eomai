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

Kordoc is also isolated behind the future chain `Application API -> HWPX Manager -> Renderer
Adapter`. Web GUI V0 has no Kordoc import, CLI, npm, workspace, or filesystem dependency. Until that
Application API capability is deployed, the UI reports `PREPARED_NOT_DEPLOYED` and never creates a
fake HWPX.

## Request Draft protocol

`schemas/web-gui/request-draft-v1.schema.json` is the canonical Request Draft wire contract. The
original request is normalized into a small immutable typed value and reviewed before submission.
The browser cannot choose a model name or raw reasoning value. The three user-facing quality
profiles resolve through a closed mapping owned by the BFF.

The accepted Application API currently supports `PLACEHOLDER_REQUEST`. V0 labels this path
`Generic Demo Mode` and maps a reviewed draft to the existing `generic-item-development` workflow.
The draft is not presented as an Integrated Science curriculum contract or a raw model prompt.

## Access patterns and data structures

- session and draft lookup: bounded dictionaries keyed by cryptographically random IDs, expected
  O(1) lookup;
- idempotent replay: dictionary keyed by `(draft ID, idempotency key)`, O(1) membership;
- timeline: ordered immutable tuple, sorted once by timestamp, O(n log n) for at most 500 events;
- DB Explorer: closed entity-to-route mapping, O(1) dispatch, with API cursor pagination;
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
