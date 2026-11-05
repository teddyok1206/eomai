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
- Total: **30,741,649,408 bytes ≈ 28.6 GiB**; observed free space ≈38 GiB after
  concurrent background use. NAS moves, DB mutations and runtime restarts: zero.
- Wheels, active/recent sources, installed environments, models, uploads, canonical
  artifacts, old/new vectors and historical failures are preserved.
- Recovery: retained wheel/Git/source archive for first-pass materializations;
  recorded `git -C /home/eom/EOM archive --format=tar <exact-commit>` and SHA for
  second-pass inputs. The machine-readable per-file plans/reports are temporary
  operational evidence, not generated Git content.
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

Source validation complete; deployment is recorded below when actually performed.
Only API's installed platform/API contracts/API package and Web need activation.
There is no new cross-service message, migration, DML, claim, execution protocol,
worker prompt or indexing change. Catalog/creative/INDEX/QUERY/chat remain on
their compatible frozen installations. Their PID/InvocationID and protected
configuration hashes must remain identical before/after.

Before replacement, retain the `98eea4bdf7cbd72aea4af77c69a80843104a4709`
API/Web rollback wheels, compare installed RECORD bytes, verify metadata, and run
the new Map reader under the real restricted API service identity. Install via
the existing wheel/Web installer boundary, restart only API and Web, then verify
HTTPS readiness, packaged assets/routes and unchanged background identities.

New Map data still requires actual authenticated administrator and source-read
permissions. Do not forge a user session or ask for repeated logins merely to
label a fixture as live acceptance. User-facing visual verification is distinct.
