# Shared provenance model reuse: actual operating release

2026-10-17 UTC. **INSTALLED / SERVICE_STARTUP_PASS / AUTHENTICATED_CONTEXT_FAIL503**.
The full incremental-RAG goal remains ACTIVE. Source, installed health, actual
context delivery, consumer activation and CPU/CUDA measurement remain separate.

## Reviewed source and unchanged boundaries

Installed source `7fcd08654d7fa8d4a030d6e302b265d5399d6191`, tree
`1ed78308522b14c2450cc1b0c57a113c511faa94` extends the existing root-scoped frozen
model cache to shared past-exam provenance. It does not omit any of the four
population captures, current permissions or source/report/Graph/policy checks.
Source evidence:154 focused tests, strict mypy2, Ruff/format and synthetic
four-phase measurements in the [design](../architecture/SCOPED_TYPED_ARTIFACT_DECODING.md#shared-past-exam-provenance-follow-up--design-before-implementation).
Synthetic speedup is not live latency acceptance. No schema/migration, DB state
machine, dependency, numerical model/space or30s client deadline changed.

Existing release materialization/admission/maintenance/provider helpers were
retargeted to exact source, wheel and previous-state hashes. No parallel deployer
or privileged broker was introduced. Protected stage:
`/var/lib/eom-release-operator-stage.7fcd0865-fjfeqw7x`; release context1.4 raw SHA
`d87d031a9cb71570cc8fbbd658af446d3ede177b4cddd192b80c7b7194d54203`.
Materialization and exact-context ADMIT both passed.

## Exact-owner drain and standard installation

At16:40:58, supported SIGTERM went only to QUERY main PID494137/invocation
`1f3ff7fa288747d6bf832906b99d9f13` and INDEX main PID494402/invocation
`d5b4b9ba83754e95b4a1f99836e5d38e`. QUERY exited0. INDEX completed the existing
four-target work, including its numerical child, then exited0 at16:53:43. A
foreground16:52 read-only observation still showed its original Workflow RUNNING
at completion; this was not treated as a timeout or reason to force/restart it.
Both owners ended with MainPID0, empty cgroups, success and exit0. No numerical
child kill, direct row update, retry identity or history rewrite was used.

Independent CHECK16:54:04 and STOP16:54:41 confirmed DB/worker/native quiescence
before stopping the eight original shared services. Standard
`scripts/api/deploy_release.sh --install` ran once16:55:05–16:56:09 and exited0.
Its supported callbacks passed PDF verification, migration0055 verification,
API role bootstrap, Catalog/HWPX role reconciliation and API isolation. Wheel
RECORD, installed metadata and fail-closed pidfd gates also passed. No new
migration upgrade or authenticated smoke was inferred from these checks.

Actual installed wheels are from
`/tmp/eom-api-build/7fcd08654d7fa8d4a030d6e302b265d5399d6191.f3WOXN/dist`,
not the earlier build-only ZIP materialization:

| Wheel | Actual raw SHA-256 |
| --- | --- |
| platform | `0c907071e43fe36b6129ff0fbb4c9e134e4ec981f56154d5d891701a70a5044c` |
| API contracts | `46cabb440789bcdef044fc2e0817cbd3c1f00855abca4ca3de0c90a273b1fc2e` |
| API | `5be412a30afc258f929d983ca861c7a2e5fc1864332baa7b6bc7c50de91b8696` |

The changed retrieval/provenance files match reviewed source bytes. Rollback
record: `/var/lib/eom-api/deployments/7fcd08654d7fa8d4a030d6e302b265d5399d6191.json`.
Previous4222ca9a wheels/record/config remain preserved and were checked before
effects. A rollback requires compatible-set/head checks, not a blind downgrade.

## Provider alignment, restoration and health

Exact provider PREPARE/SELECT/START passed. Only QUERY's API provider, its unit
configuration hash and nonsecret Chat release pin changed; predecessor bytes
remain under `/var/lib/eom-query-provider-7fcd0865`. Eight original shared
services were restored active with NeedDaemonReload=no.

- API PID824658, invocation `65d4a348a12f40789c808257fbbcc3be`.
- Catalog PID824620, invocation `8ee64006ab294fd9b45ea3bb624b97ff`.
- QUERY PID827051, invocation `83881eaa2f8e417b9919da8d9b2dbba7`;
  actual OWNER_READY16:57:21, socket UID990/GID985/mode0660.
- INDEX PID827407, invocation `6294754abb174c8e85b8b0fac0776d43`;
  actual SERVICE_STARTED16:58:02. Its original config/runtime/unit hashes and
  numerical CPU default are unchanged.
- API live=LIVE/ready=READY16:58:20; all four services active again17:03:24.

This is installed/startup evidence, not proof that an authorized context can be
delivered within30s, that all sources have vectors, or that GPU is active.
Last routine INDEX observation16:36:16 reported653 encodings/653 bindings,
170 immutable index revisions/six logical indexes. These are view relations,
not653 unique Items or full corpus coverage. Routine observations remain30min
apart; foreground drain/HTTP handles are separate operations.

## Original request and honest authentication boundary

After deployment, the old same-memory-session observer actually received401
`AUTH_TOKEN_EXPIRED` at16:58:32. Supported QUIT terminated it; logs/state remain.
No credential extraction, permission change or authentication TTL override was
used. A new observer keeps the official token pair only in memory and uses the
official refresh endpoint within its existing expiry/refresh budget, checking
unchanged operator/session/authenticated_at through `/auth/me`. Ten isolated
synthetic adapter tests passed; these are not live-refresh acceptance.

The first new login was rejected with401 `AUTH_INVALID_CREDENTIALS`17:06:03.
That observer exited and its exact failure log/state were renamed for retention.
At the user's request the identical reviewed script was restarted in the same
tmux window, not with a new numerical request. Login actually passed17:09:09;
the same original Workflow was READY17:09:21. At17:10:01 the actual context read
returned503 `SIMILARITY_CONTEXT_UNAVAILABLE`. The observer remains live at its
supported AWAIT_EXPLICIT_REPLAY prompt, retaining only the current memory session.
This is an actual unresolved read failure, not PASS inferred from READY, source
tests or health. Further repeated requests are not a diagnostic substitute;
stage-level measurements are needed before another performance change.

Fixed key `goal-http-reference-query-20261015-01`, operation
`queryprepare_a2c36b2744284b65971b6025f7356432`, Workflow
`workflow_a0833f96b5154c3da4c5e5961eb9a209` and request SHA
`sha256:258c0567f807fb1e4c43b4107809acb7dec5a37add2c7c06082c2b26e3e0ae3f`
are unchanged. The validator reads/replays existing work; it does not regenerate
the numerical query or submit a new model/key. It checks two equal authorized
contexts plus wrong-header409 before writing an acceptance receipt.

Operation metadata and exact helper/output hashes are retained under
`/tmp/eom-provenance-read-release-BnDPXZZA`; original HTTP continuation state and
any future acceptance are under `/tmp/eom-query-http-canary-8oxU2rnJ`. Credentials,
full logs, prompts and content are not committed or sent to Slack. Shared cache
source tests/installed health are not relabeled C1–C5 or full-goal acceptance.
