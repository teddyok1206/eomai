# Map and recoverable local-build cleanup

## Scope

The user requested no NAS relocation: obsolete local build/temporary files only.
DB fields, Item metadata, textbook/past/creative/AI sources and vectors are not
cleanup targets. Move the existing navigation to Data as `Map`, implement bounded
published Graph exploration and retain the old coverage screen as a learning
diagnostic. [Design](../architecture/KNOWLEDGE_MAP_READ_DESIGN.md).

## Cleanup completed

- First plan: 33 obsolete API source copies, 17 Web installed simulations and
  18 Web staging copies; 4,469,813,248 bytes freed.
- Second plan: 621 `source.tar` files older than 14 days; 26,271,836,160 bytes.
  Every retained wheel's commit/tree/archive SHA matched, and Git reproduced the
  exact archive bytes before admission. Recheck filesystem identity, live process
  references and SHA before unlinking only each admitted file.
- A final Git reachability audit restored 14 archives (311,429,120 bytes) whose
  commits existed only in reflogs. These must not depend on future Git GC.
  The other 607 removed archives have commits reachable from retained refs.
- Net total: **30,430,220,288 bytes ≈ 28.3 GiB**; observed free space ≈37 GiB
  after concurrent background use. Cleanup NAS moves, DB mutations and runtime
  restarts: zero.
- Wheels, active/recent sources, installed environments, models, uploads, canonical
  artifacts, old/new vectors and historical failures are preserved.
- Recovery: retained wheel/Git/source archive for first-pass materializations;
  recorded `git -C /home/eom/EOM archive --format=tar <exact-commit>` and SHA for
  second-pass inputs. The per-file plans/reports and recovery reconciliation are
  preserved in `/var/lib/eom-map-release-20261105/`, not generated Git content.
- Four creative workers resumed naturally when the local disk reserve became
  available. Do not infer cumulative registered counts from a cohort cursor.

## Source and browser validation

Focused source tests cover frozen pin/schema/resource parity, missing/stale Graph,
permission and administrator boundaries, revoked source metadata, indexed bounded
adjacency, no work creation, preserved coverage, boot navigation and DB behavior.
Ruff format/lint and strict targeted mypy pass. Wire-contract audit passes.
Real Chromium fixture tests cover Map node/edge selection, expansion, layer filter,
preview, DB handoff, stale account response rejection and existing DB/guide/request
screens. Fixtures do not count as authenticated live user acceptance.

Read-only checks of the actual existing Graph returned a ~32k-node/~71k-edge
snapshot in bounded neighborhoods. Example queries took 0.02–0.22s. Textbook,
past-exam and creative layers all appeared; no model/GPU invocation was made.
This is not a performance guarantee or an original PDF visual inspection.

## Compatible rollout

Source validation complete; final deployment is recorded below when performed.
There is no new cross-service message, migration, DML, claim, execution protocol,
worker prompt or numerical indexing change.

An initial API/Web-only attempt was withdrawn: the existing QUERY service has
`Requires=eom-api.service`, so stopping API also stops QUERY. Restoring package
bytes while the successor process remained active also correctly failed the
current-provider identity fence. Restored the old package set, stopped/restarted
the receivers after the existing one-second metadata-epoch guard, and restored
QUERY. API/Web/QUERY returned active; INDEX/creative/Catalog PIDs stayed unchanged.
These failed deployment receipts are retained, not reinterpreted as acceptance.

The established compatible-set rollout is required because QUERY configuration
pins the API provider's commit, wheel and code-member hashes. Updating those
also changes the dependent public/private wrapper configuration hashes. Reuse
the existing release codecs, Catalog/QUERY bindings and runtime-environment
switches; do not weaken the provider checks or detach systemd dependencies.

Before replacement, retain the `98eea4bdf7cbd72aea4af77c69a80843104a4709`
API/Web rollback wheels, compare installed RECORD bytes, verify metadata, and run
the new Map reader under the real restricted API service identity (passed,
about 0.25s). Gracefully drain the creative producer through its supported SIGINT
handler: existing workers finish naturally. After command/lease/RPC quiescence,
activate the compatible API/Web/Catalog/runtime set and exact provider hashes,
restart the original producer, and verify HTTPS and all receivers.
The frozen INDEX and numerical GPU runtime, original data, execution history,
credentials, model files and vectors must remain unchanged. No migration runs.

New Map data still requires actual authenticated administrator and source-read
permissions. Do not forge a user session or ask for repeated logins merely to
label a fixture as live acceptance. User-facing visual verification is distinct.

## Final installed acceptance — 2026-11-05 17:52 UTC

- Installed compatible release: `0b5088a8ab88d45cd2c6e3e4ccbd9feb3afe17d9`.
  Source feature commit: `11ff16cb`; packaging/OpenAPI follow-up: `0b5088a8`.
- `MAP_COMPATIBLE_COMPATIBLE_RELEASE=PASS`. Exact installed API wheel members
  and Web RECORD (60 runtime files) verified; migration stays `20261105_0073`.
- QUERY implementation remains `7f0566c4`, with the exact successor API-provider
  commit/wheel/code hashes and dependent wrapper hashes. Existing release codecs
  verified all bindings; no permission/policy or credential change.
- INDEX source `525ae472`, PID `4045657`, invocation
  `46a57cf5012c49ee9a05405f1eddaf9d` and all numerical/GPU settings preserved.
  Creative producer drained naturally, then resumed with its unchanged scope and
  configuration. No original worker was killed, history rewritten or model rerun.
- Actual restricted `eom-api` identity: Map read, source detail, exact Item
  revision/manifest handoff through the existing DB projection, and identical
  pinned replay all passed. 87 nodes/71 edges, mixed textbook/past/creative
  layers; combined read/handoff check 3.27 seconds; Map model calls zero.
- Actual HTTPS: ready PASS; Map JS/CSS/application assets match installed SHA;
  unauthenticated Map read denied. Manual user browser verification NOT_RECORDED.
  Subsequent user feedback, “조회 잘 되네”, closes **MANUAL_MAP_READ=PASS**.
  This confirms actual screen lookup only, not every interaction/content-quality
  gate. Appended `manual-map-read.json`; the earlier immutable acceptance stays.
- Combined focused regression run: 142 PASS; strict targeted mypy, Ruff
  format/lint, wire mirror audit and real Chromium Map/DB/guide/request/preset
  fixtures PASS. A native Hancom/content-quality check is not part of Map.
- Protected release evidence:
  `/var/lib/eom-map-compatible-release-v2-20261105/activated.json` and
  `map-acceptance.json`. The initial withdrawn rollout/recovery records remain
  in `/var/lib/eom-map-release-20261105/` with the cleanup manifests.

The Map shows actual bounded Graph metadata and Item previews/DB handoff.
It does not add a new raw textbook PDF/media download contract or generate
quotations, reasoning, missing page locators or similarity scores.
