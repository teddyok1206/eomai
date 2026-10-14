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

## Actual compatible receiver/owner installation — 15:31 UTC

Source `5018ad2df4d4f882b2d843876fedf38190e4db43` passed the complete independent
release build/RECORD/definition inventory and owner-pair-only transitive import
proof. Its protected owner pair is installed INACTIVE; numerical CPU/operator
prefixes and source policies are unchanged.

The standard shared API release is installed with schema head0055 unchanged.
The existing protected release-operator context1.4 verified the migration, native
PDF runtime, API/Catalog/HWPX roles and API isolation; no migration upgrade ran.
The exact supported quiescence projection found no executable work/leases/chat,
active Workflow commands0 or PROCESSING API idempotency0 before the window.
All9 original services are active again, no daemon reload pending, API LIVE/READY
PASS. The actual index owner `eom-embedding-index-owner.service` remains inactive,
disabled and successfully drained; that is not an automatic-coverage completion.

| Actual delivery wheel | Raw SHA256 |
| --- | --- |
| platform | `682d0d9ced677e82fa7dd45cbf7bbb16917bc1af1e5e65adc03ee5fc223f89c7` |
| API contracts | `b1b35ed86e7ecfd3df0ea4390f8207f97b5285bc3e6fa18668667137bd164c41` |
| API | `e3b29f4c74bcbd118d11115793629a20ac791048ef650300420e466bcf1a54e4` |

Actual UID990/no supplementary groups verified the protected installed provider,
all9 exact code pins and real fixed API socket peer. Both new purpose methods
are present. Missing-bearer HTTP smoke returns401. **No genuine operator capture,
QUERY/GPU forward or current-source permission is established by these probes.**
Rollback metadata: `/var/lib/eom-api/deployments/5018ad2df4d4f882b2d843876fedf38190e4db43.json`.
Independent root-private context: `/var/lib/eom-release-operator-stage.5018ad2d-1xn2j23m/`,
raw context SHA256 `f4b45eeb23d33850117b8e9f9775f89daf5cdd30a6a49a312764a2e18a6d9142`.
Build-only and actual delivery wheel hashes differ; source/tree/archive and
reviewed code members were independently checked, not assumed from filenames.

Two operational invocation failures are retained: the first pre-stop probe used
an incorrect unit name and refused before changing services; the next isolated
`runuser` deployment child could not reuse the original sudo TTY ticket and
refused before replacing packages. The unchanged services were then updated by
the standard deploy from the ORIGINAL tmux pane, without another password,
sudo policy/TTL change or credential storage. These were not source/state bugs.

Evidence: `query-purpose-{owner-inactive-install,owner-pair-proof,release-stage,
release-admission,live-preflight,compatible-release-window-reviewed,
compatible-api-install-reviewed,installed-provider-preflight}.log` in the same
evidence directory. Slack milestone `devreport_b1802f0cfbdc407fbc0b15cc58782ee3`
reported installation separately from remaining QUERY/consumer/GPU work.

### Final contract-alignment follow-up

The wider OpenAPI inventory correctly found an omitted generated snapshot update
(30 PASS/1 failure); runtime calls and the new receiver code worked, but packaged
documentation still described only1.0. Regenerate the canonical snapshot/hash
with the existing offline exporter. Preserve the predecessor wire schema bytes.
The independent installed-wheel inspector now constructs the ACTUAL installed
application with explicit synthetic invalid DB credentials, compares its routes
with the packaged snapshot, and disposes its unconnected engine. Merely comparing
two identical stale snapshot/hash files can no longer pass the release gate.
No production settings, credentials or DB connection are needed for that check.
The corrected snapshot belongs to the next exact compatible release; do not
replace a packaged file behind5018ad2d's RECORD or call this a new QUERY execution.

Corrected source regression, including the actual OpenAPI equality and release
inventory: **424 PASS /44.80s** (overlaps392). Ruff/format/shell syntax/diff PASS.
