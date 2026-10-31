# Item DB category and approval parity

Scope: categories 기출 / 창작 / AI; independent approval filter and per-row status;
creative source metadata/filter/file/PDF parity before and after registration;
Graph-validated similarity/registered assembly navigation. No migration, model
invocation, approval mutation, new queue or source/Graph/index activation.

## Gates

- Final focused API/Web/Catalog regression: **133 PASS**, including actual Chromium
  fixture, preserved source metadata/files, approval filters and category separation.
- Source/browser alignment and actual Chromium fixture: PASS; live writes = 0.
- Fresh disposable PostgreSQL suite: 29 PASS, including creative approval + metadata
  predicates, stale source exclusion, AI/creative separation and scoped keyset replay.
- Ruff and mypy of affected core: PASS.
- One rerun of the broader persistence suite in an already-used disposable DB hit
  an existing global-count fixture expectation (5 instruction rows vs expected 3).
  This was not interpreted as a production defect or fixed by changing expected
  counts. A fresh disposable DB was migrated/reconciled and all 29 tests passed.

## Deployment boundary

The shared API Python is also used by runner/maintenance processes. Preserve the
running INDEX, creative owner, numerical prefixes and selected controls. Shared
runner/maintenance consumers pause during installation; the three creative workers
continue using their complete existing private release. Web uses the existing
build/install procedure after API readiness.

An initially staged API-only selector was retired: the protected identity-provider
observer requires **no API drop-ins** and the existing fixed installed-code paths.
The original isolation/process-identity checks and the subsequent provider rejection
were preserved, not bypassed. Do not accept a general PYTHONPATH exception or weaken
the provider observer. The final selection installs the three reviewed wheels into
the established shared API environment and retains the original API unit/entrypoint.

Before activation verify wheel SHA/RECORD, installed member bytes, exact API source,
packaged schemas/OpenAPI and unchanged QUERY identity-provider code members. Capture
preserved PIDs and protected config hashes. No source checkout/editable install is
used at runtime. QUERY restarts after API readiness, with its existing owner source,
configuration and access-policy pins unchanged. Its prior failures remain failures.

Rollback restores the predecessor API/platform/contracts wheel set and previous
workflow-runtime source pin, then the prior Web wheel if needed. The existing
protected predecessor wheel set is under
`/var/lib/eom-release-operator-stage.4cc9546c-vsq61blf/dist` (API source `5fdda815`).
Do not restart INDEX, interrupt private creative workers or rewrite failed records.
No temporary API selector or deployment framework remains active. The temporary
source installer guard was also removed after retiring that selector.

## Acceptance boundaries

Actual user browser clicks are not implied by fixture PASS. Record installed
release, HTTPS assets/readiness, service isolation, actual read-only DB projection
and remaining manual UI confirmation separately after deployment. No user password
is reset and no account is impersonated for verification.

## Installed acceptance — 2026-10-31 UTC

- API/platform/contracts and Web source: `f419383cd3890a5b829baad97db3b88c5b90a124`.
  Three shared wheels' **2,460 members** match; Web installed verification covers
  **52 files**. The standard API unit/entrypoint is active with **no drop-ins**.
- API wheel SHA-256 `437324e6dd911b707b71ae1fa3e4faebfdfd3bd30f6f92352ce63ab3b29ccdcc`;
  contracts `d95268c88d853d9c392c0f1544e038088e7c03b9799b72c89eaedcffe89052d3`;
  platform `8bda1553f4e4e4d8b723fd9d06a78b35931f02ec557903fa98f404d51e251776`;
  Web `84cb8f2b205b50389b335382cbfa05c4d18442de9e8a2fe89b80b7cd398ac1de`.
- API PID469955, QUERY PID470146: active. QUERY was observed active after the
  corrected deployment rather than treating a successful `systemctl start` alone
  as acceptance. Protected identity-provider checks remain unchanged.
- INDEX **PID225508**, creative owner **PID3724425**, Catalog **PID3760261** are
  unchanged. INDEX/QUERY configuration and resource/access-policy pins are unchanged.
  Shared runner/maintenance/HWPX control processes were paused/restarted for pip;
  existing private creative workers and GPU numerical work were not stopped.
- Final actual-process API isolation verification **PASS** (all allow/deny probes).
  HTTPS readiness **PASS**; `index.html`, `item-db.js`, `item-db-similarity.js` bytes
  match source; unauthenticated AI read returns **401**, not 404/500.
- Installed API service-account **read-only metadata** probe PASS: creative approved
  and unregistered samples match their filters; generated AI samples include both
  IN_REVIEW and APPROVED. These are bounded samples, not total corpus counts or
  claims of an authenticated human session test.
- User confirmed the changed GUI matches the request: **USER_CONFIRMED_LAYOUT**.
  This is not expanded into a claim of manual testing of every permission branch.
- Both disposable databases were removed using the guarded cleanup command; no
  production DB records were modified. A pip-retired API directory was moved out
  of the import path and retained at
  `/opt/eom/api-releases/f419383cd3890a5b829baad97db3b88c5b90a124/pip-retired-api`.
- Root-owned bounded release evidence:
  `/opt/eom/api-releases/f419383cd3890a5b829baad97db3b88c5b90a124/shared-activation.json`.
  Predecessor Web wheel remains under
  `/tmp/eom-web-gui-build/f1a7ada42c13241c4b9e235d02badc0f94457334.lXP21L/dist/`,
  SHA-256 `7dfb953d087ab304dc7cce728cd3d2d7539c3cf0f0d602d4f9832205743dd3e4`.
