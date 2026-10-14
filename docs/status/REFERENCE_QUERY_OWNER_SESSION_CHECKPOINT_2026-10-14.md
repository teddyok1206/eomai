# Reference QUERY / device comparison owner-session checkpoint

2026-10-14 UTC. Source implementation and isolated tests, **not live activation**.

The current genuine persistent seed and bounded delta remain completed; vectors/
bindings2, immutable revisions2, coverage2/520. The owner is quiescent after a
graceful drain. No new native QUERY, GPU forward, source authorization or production
DB update was performed for this checkpoint.

## Exact change

The seed-only `operator-owner-session-capture/1.0` schema, parser, serialization
and provider method remain unchanged. The schema-first1.1 successor explicitly
labels only `REFERENCE_QUERY` and `LOCAL_EMBEDDING_DEVICE_BENCHMARK`; its response
binds both declared purpose and exact request hash. API authentication and the
single-use held-peer transport reuse the same existing Identity implementation.
This label is not execution permission: native owners must independently recheck
the actual operator, current session and pinned source/access controls.

No DB schema, migration, worker protocol, queue, new dependency, stored credential,
TTL change or automatic refresh/retry was introduced. The installed-provider
observer additionally pins both exact contract-code members, so this controller
must not be paired with an older API that lacks the successor.

Legacy schema raw SHA256:
`bb7571ce9decf18cff2d99e4dc13f2d92f1c237c65ab05fe243ce4d27fac4436`.
New schema and packaged mirror raw SHA256:
`fa196b772abf756f0b4d646fa0a77f2be770a66801f1706bea474393e1d6c923`.

## Executed gates

- Source contracts/API/provider/native-owner regression: **392 PASS /39.32s**.
- Genuine guarded disposable PostgreSQL authenticated-session fencing/writer
  concurrency: **19 PASS /8.34s**, migration head0055; production was not pytest's
  target. Expiry, revocation and original lock boundaries remain unchanged.
- Strict mypy6 source modules, Ruff lint/format and diff checks PASS.
- Synthetic real HMAC capture plus held socket tests cover both declared purposes,
  exact original expiry, single-use import, late purpose/version/provider/socket
  mutation, legacy downgrade, revoked login, rate denial and content-free failure.
- Earlier190-case focused run and failed151/1 fixture inventory run are retained,
  not added to392. The fixture now expects the two additional pinned code files;
  no production guard was relaxed. The only regression warning is the existing
  Starlette/httpx TestClient deprecation; no dependency was changed to hide it.

Evidence directory: `/tmp/eom-identity-provider-install.nAaycoDM/`;
`query-purpose-capture-{focused,regression,postgres,mypy}.log`.

## Next / honest limits

Build and verify the exact compatible API/owner wheels and a recoverable release
set before actual operator capture. Do not relabel QUERY as a seed, reuse an
expired authentication observation, or alter production rows. No new Studio
login has been requested for this change. Reuse the same sudo pane when an actual
installation needs it; no keepalive or password/token storage.

Then publish the existing exact QUERY definition/policy, execute and read one
genuine committed query with current source/index pins, verify same-key replay,
and attach existing consumers. Automatic remaining coverage and GPU comparison
are still original goal tasks, not completed by the transport tests.

Design: [owner/session boundary](../architecture/LOCAL_EMBEDDING_OWNER_SESSION_IMPLEMENTATION_BOUNDARY.md).
Preserved live evidence: [seed/delta activation](LOCAL_INDEXING_ACTIVATION_2026-10-14.md).
