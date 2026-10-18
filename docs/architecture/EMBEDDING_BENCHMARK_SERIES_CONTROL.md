# One original benchmark series: root control rendezvous

Design before behavior,2026-10-18 UTC. Continues
[the six-launch composition](EMBEDDING_BENCHMARK_EXECUTION_COMPOSITION.md).

1. Responsibility: let the admitted owner connect each newly reserved original
   execution to one already-running, operator-selected root controller. Reuse the
   existing per-launch root driver, control channel and protected stage reader.
   This is a finite rendezvous, not a persistent scheduler or new queue.
2. Canonical input is the original selected BenchmarkOwnerRequest1.0 and existing
   BenchmarkLaunchAssociation1.0. Source/user/Job permission remains the actual
   Orchestrator admission before staging and at every continuation/publication.
3. Pin request/revision/hash, exact owner PID/UID/GID/birth, installed controller
   release and selected CPU/CUDA backend pins. The first original association
   fixes the Job; all six executions must be distinct and in prescribed order.
4. The fixed root socket name uses the declared benchmark revision's complete
   identifier suffix, not a truncated content hash. Each received association
   resolves its exact local stage and compares all bytes/identities before effects.
   No filesystem scan, latest selection, arbitrary path or NAS access by root.
5. Access patterns: one fixed-name socket lookup, six ordered accepts, set-based
   execution membership; O(6) state and O(1) stage lookup. Existing Job/lease/
   idempotency owns persistence; no DB/index/cache changes.
6. Reuse the closed association/prepared/resources/completed frames without
   changing released schema bytes or worker behavior. A bounded initial receive
   learns the association from the exact selected kernel peer; the same connection
   then retains the association's original compute/control deadlines.
7. The root controller's finite accept deadline does not authenticate anyone,
   renew a human session or extend a staged compute deadline. Any original failed
   or uncertain execution stops the series. No reconnect/restart/new identity.
8. The existing root-only per-execution entry remains supported. Share root launch
   effects and listener ownership with the series route instead of duplicating
   prepare/ACK/cleanup/publication logic. No worker sudo or privileged API endpoint.
9. Owner connection verifies root socket metadata, exact root process birth and
   current original authorization. Root independently verifies exact owner peer,
   owner birth, selected request and stage. Peer metadata is not source authority.
10. Runtime selection is explicit; CUDA host/inventory capture and actual physical
    lease/cleanup stay with their existing owners. Root returns only persisted
    original machine completion; it cannot attest numerical/source success.
11. Manually discovering six random execution directories is simpler but requires
    races/scans and does not provide an actual operator entry. One fixed bounded
    rendezvous keeps original execution generation on the existing owner side.

Source/package/actual UID transport tests are separate from six genuine model
runs, numerical/resource/regression gates and coherent QUERY/DOCUMENT default
selection/rollback. No interactive login or fresh-auth substitution is permitted
during the user's24-hour unattended interval.

## Implemented source boundary — 2026-10-18 UTC

The root accepts only its selected actual owner process, consumes the existing
association once, resolves that exact staged execution and calls the same root
prepare/CPU-or-CUDA/resource/cleanup implementation as the known-stage entry.
No directory discovery, model retry or new key is used. The single listener's
inode ownership/cleanup is shared; an existing or replaced socket is never removed
as if it belonged to this invocation. Per-execution native sockets are unchanged.

The owner now uses the series rendezvous. Its read-only installed preflight checks
the exact listener's existence/root ownership/group/mode before a Job reservation;
that is not root liveness or source admission. A race after preflight preserves
the original uncertain execution rather than reconnecting/replacing it. Root's
maximum900-second accept window and ten-second initial frame bound do not renew
authentication or extend the association's original compute/control deadline.
Wrong peer connections are rejected before parsing, with at most eight rejects
per accept; a bad original request/order/Job/birth or failed/unknown launch stops
the entire finite series. All source/Job/continuation checks stay on the owner.

Related50 source suites **1326 PASS /252.26s**; strict mypy7 changed production
modules, Ruff/format14 and diff checks PASS. Prior50/47/17/13 focused subsets
overlap and are not summed. Actual same-UID Unix framing, all six ordered stages,
CUDA resource exchange, wrong-original/failure/uncertainty refusal, absent-controller
preflight and inode replacement are exercised. Positive root identity, stage
reader, unit drivers, installed metadata and GPU counters are synthetic; actual
nonroot controller/client denial is separate genuine negative process evidence.

Seven first-draft rendezvous positives failed because generic Mock disallows
attributes beginning with assert. Fixtures now explicitly declare the intended
metadata methods; production metadata checks were not relaxed. Shared selection
validation preserves the old known-stage behavior: bad backend/request/CUDA capture
fails before waiting for any frame, and is revalidated before root effects.

The packaged real root/workflow-owner peer/DAC/bootstrap case is added and the
privileged cohort collects11 tests. At this source checkpoint it has NOT_RUN;
collection is not positive OS acceptance. No numerical/model, operating DB,
service/unit, credential, selector or default change was made. CPU remains default.
No schema bytes, migration or dependency changed. The earlier79f988b1 disposable
timing23 proof remains historical coverage of unchanged timing/SQL code, not a new
privileged/runtime result for this source.

Still required: a reviewed installed operator composition must supply actual
captured CUDA host/inventory and selected machine pins, retain their lifetime,
and start the finite root entry for the actual admitted owner process. This source
does not select policies, create an administrator session or expose a privileged
network API. Fresh-user/source gates, six real models and numerical/resource/
regression/default/rollback acceptance remain OPEN; original C1–C5 scope is intact.

## Passive installation and actual private OS proof — 2026-10-18

Code candidate `93e9204f9985551b8df636ea4886ad9dbad3190f` passed the standard
three-wheel/RECORD/installed-simulation build and was pushed. Directory:
`/tmp/eom-api-build/93e9204f9985551b8df636ea4886ad9dbad3190f.CH46oP/dist`.
Platform wheel raw SHA256:
`fb74f37f94c1374632b0d2b0aca41e590541dfa0e0588b2c356ddca8b2b14799`;
API-contract wheel raw SHA256:
`123a2a4ca1ba7a30042212e7c076ff3b41d58669aea02e5fdc02718e3205a88f`.

The existing protected installer559ada516fe9d46f57926aad70699e81deba5f1a18b4e25e3f6e6bcdf1384b71
installed those exact two wheels to the separate passive owner prefix
`/opt/eom/embedding-owner-releases/93e9204f9985551b8df636ea4886ad9dbad3190f`.
No current selector, live service, numerical prefix, unit or default was changed.
The first operator helper then failed before tests because its copied import audit
still named the removed Orchestrator resource-client module. Original installer
stdout and failed wrapper remain preserved; the original exception content was not
retained by that wrapper (only stderr SHA0df06141e8ffc613b56eae84354038da7b08f595efe28dbeefdc57e5c612e58a).
Independent package inspection established the obsolete target's absence and the
completed passive install. No compatibility alias or production workaround added.

The read-only resume verified installed wheel hashes and all16 original fixture
bytes, used the current Catalog public module, and did not replay installation.
Its first actual OS cohort was10 PASS/1 FAIL: the new test's root-owned711 parent
allowed traversal but not the retained O_RDONLY ancestor directory descriptors
required by the production resolver. The child correctly refused the preflight;
the parent then timed out. Production directory/peer/authority checks were kept.

Only that private test parent now uses root ownership/the actual owner group and
0750, matching the retained-FD boundary. A new exclusive fixture copy reused the
same immutable installed production bytes: **11 privileged tests PASS/no skips**,
including actual root/workflow-owner UID/GID/PID/birth, root socket DAC, original
association/prepared/completion framing and owned-socket cleanup. The child execs
the explicit API Python with no supplementary groups, imports only the protected
installed package, and confirms no optional ML import. The10 earlier DAC/ACL/
environment/resource cases are rerun, not summed with historical results.
Synthetic administrator/source callbacks, selection/completion and GPU counters
remain synthetic: this does NOT prove real unit/model/source/IAM/lease cleanup,
performance, six genuine launches, device default or consumer acceptance.
The isolated fixture cohort also retains its nonblocking unknown-marker warning;
no runtime validation was relaxed to remove it.

Evidence root:
`/opt/eom/embedding-benchmark-os-evidence/93e9204f9985551b8df636ea4886ad9dbad3190f`.
Original failed helper raw:
`f4e3ec5432ef7e38fd783f59670cb974406cd939f23296682c98f34903e0507e`;
first resume raw:
`bea730629afcd0961f98ad515bb428ec7543487dd848180ad8718521246d5ad9`;
successful fixture-v2 helper raw:
`243751ca627b263cc06beee967064b10e117f3491725e93944bc2e94230fc654`.
Success lives under `series-control-fixture-v2`, while initial10/1 failure stays
under `series-control-resume-1`. Successful test stdout raw SHA256:
`fd36cbeec056060145090c0b48599627677c9d7e76259123407be319c3bec774`;
fixture-v2 archive raw SHA256:
`5830ce507e464e597f2425d11e05629dfd2dfbd060e2d59991b1bbf1194e8017`.
Protected readback01:49 UTC confirms the exact successful result/stdout and11/no
skips. All finite helpers are terminal. Source1326 evidence applies to unchanged
production code; the later test-only parent correction is separately pinned here.

No login prompt, credential persistence/TTL bypass, model, GPU lease, production
Job/DB, NAS publication or activation occurred. Root helpers use the same EOM2
noninteractive sudo TTY. Only private test namespaces were created/removed. The
actual root CUDA capture/operator composition and full original goal remain OPEN.
All zero execution counts above refer to these helpers, not the independently
running INDEX service and its ongoing authorized work.
