# Item DB category and approval parity

Scope: categories 기출 / 창작 / AI; independent approval filter and per-row status;
creative source metadata/filter/file/PDF parity before and after registration;
Graph-validated similarity/registered assembly navigation. No migration, model
invocation, approval mutation, new queue or source/Graph/index activation.

## Gates

- Focused API/Web/Catalog regression: 132 PASS before final small label/guard edits.
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
running INDEX, QUERY, creative owner, numerical prefixes and selected controls.
Use the same immutable installed-wheel closure pattern already used by Catalog
and creative owners: stage the three reviewed API/platform/contracts wheels under
`/opt/eom/api-releases/<commit>/site-packages`, with root ownership and read-only
package files. API alone selects this closure using its isolated Python boot in
`/etc/systemd/system/eom-api.service.d/45-eom-api-installed-release.conf`.
The existing API unit identity, network/filesystem sandbox and secret paths stay
unchanged. Web uses its existing build/install procedure after API readiness.
This is a bounded operational composition, not a new deployment framework.

Before activation verify wheel SHA/RECORD and installed member bytes, exact API
source, packaged schemas/OpenAPI, unchanged QUERY identity-provider code members,
and API service-identity imports. Capture preserved PIDs and protected config
hashes. No source checkout or editable install is used at runtime.

Rollback removes only that managed API drop-in, reloads systemd and restarts API
to the preserved shared installed predecessor, then restores the prior Web wheel
if necessary. Old wheels and the release record remain available. Do not restart
INDEX or rewrite failed records. A later **shared** API install must explicitly
retire this drop-in; the normal installer fails closed while it exists so a newer
shared package cannot be silently shadowed by an older scoped API.

## Acceptance boundaries

Actual user browser clicks are not implied by fixture PASS. Record installed
release, HTTPS assets/readiness, service isolation, actual read-only DB projection
and remaining manual UI confirmation separately after deployment. No user password
is reset and no account is impersonated for verification.
