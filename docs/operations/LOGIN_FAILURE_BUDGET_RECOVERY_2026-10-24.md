# Login failure budget and local account recovery

## Reviewed scope

The user requested permanent deployment of the side-conversation fix described in
`staging/login-recovery-20261024/summary.json`. That operational handoff records
already-completed account recovery, not permission to reset those passwords again.
No account/password change or deliberate failed login against real users is part of
this release. Generated handoff/test artifacts are not source-release inputs.

The API previously consumed a per-username process-local limit even for successful
logins. That cache survived a credential reset and could block a recovered correct
password. The browser also collapsed HTTP429 into a generic login failure.

## Responsibility and invariants

- Identity's existing credential rows, lockout state, active status and session
  revocation remain authoritative. The API retains the pre-auth global burst limit.
  Its per-username cache paces only failed responses after credential verification;
  a verified successful login clears only that username's failure bucket.
- `BoundedRateLimiter.discard()` uses the existing locked keyed collection, O(1)
  expected lookup/removal. No second cache, persistent derived counter or database
  migration is introduced. Concurrent successful/failed attempts cannot bypass
  authoritative database credential locking or make a correct credential depend on
  a stale process-local username bucket.
- The official local recovery application adds a general active-account command
  pinned to Operator ID, expected username and resource version. Existing trusted
  local `eom` OS authorization, password policy, row locks, forced password change,
  target-only session revocation and audit transaction are reused. Legacy
  administrator recovery still requires an ADMIN target. Roles are never changed.
- CLI remains presentation/typed-command construction; Identity owns the mutation.
  No HTTP emergency-reset endpoint or remote recovery privilege is added. Confirmation
  mismatch or failed local authorization occurs before reading password material.
- The login UI safely distinguishes401,429 and service failure using plain-language
  messages and a validated request identifier rendered with `textContent`. No server
  traceback, credential or arbitrary response prose is displayed.
- Existing logical Operator identity, resource version and audit/session history
  remain distinct. Deployment runs no recovery command or password reset.

## Independent review evidence

The original handoff reports120 focused and70 separately installed recovery tests.
Those are historical evidence, not this review's rerun totals. This review reran107
tests across rate limiting, login/reset recovery, official local/approved recovery
and browser error handling. It added three persistent synthetic CLI tests for pinned
command wiring/no-secret output, confirmation rejection and OS-owner rejection before
password reads. No live database/account mutation or HTTP failure test was used.

Ruff/format/JavaScript syntax and scoped strict mypy for the four changed Python
production modules passed. An unrestricted dependency-following mypy invocation also
reported two pre-existing errors in `similarity_role_preparation.py` (outside this
login change); do not claim a repository-wide type-check PASS.

## Compatible release and verification boundary

Commit only the ten handoff-listed files and this note. Preserve the concurrent GPU
authority/recovery changes unstaged. Build an immutable API/platform/Web release
from that exact clean commit, not the dirty shared checkout. Retain installed
rollback artifacts and use the existing release/isolation/compatibility checks.

The previous native benchmark is terminal, its CPU process and retained descriptors
are gone, and GPU memory returned to2MiB. Do not alter numerical worker d381, CPU/CUDA
prefixes, model bytes, host receipts, lease inode, Graph/policy pins or outputs during
the login release. The API provider release changes, so later benchmark execution
must select and verify the new installed API/wheel/code identity rather than force
the old19df pin. Reobserve current INDEX/QUERY identities after deployment.

After deployment, verify actual HTTPS login with a genuine operator, service/asset
readiness and installed source/RECORD identity. Credential/limiter/reset negative
cases stay synthetic or disposable. Create no new password reset and deliberately
fail no real account. Log out only the test session if it is not being retained for
the explicitly authorized next operation. Record actual live evidence separately;
source tests and prior user verification do not prove this release's live result.

Deployment and final authenticated HTTPS verification are pending at this note's
initial commit. Update operational evidence after the actual release.

## Actual release (2026-10-24 04:24 UTC)

Login-only source `b87cc11c9a7a853c80877fdd39838b01292fb6e5`, tree
`c10b628ddabeead8c85d6cf1e3859da2527f47ca`, was committed/pushed separately from the
still-uncommitted GPU changes. A clean local clone at that exact commit supplied
the existing build/release scripts; only temporary caller script root assignments
changed. The shared dirty checkout was not stashed, overwritten or used as source.

Standard protected release context1.7 stage
`/var/lib/eom-release-operator-stage.b87cc11c-l6ijys6t`, context SHA
`aed679fb2b12e1f0dc4a07f29379ffae323b59b5451a840401dd2d2de9d38847`, passed ADMIT.
The normal installer passed PDF runtime, migration0058 verification (no upgrade),
API role bootstrap, Catalog/HWPX reconciliation, RECORD/metadata and API isolation.
Actual installed API wheels are from `b87cc11c…Mh55ks`, not the earlier build-only
materialization. Their SHA-256 values are:

- API: `2a1245cf2ebf83219ae4036c3d4a75bae778f3bb8aa3334e9abbf91f67b2f7e2`
- platform: `60dfcf24004b3227b64a538323a194f466f70938698dc043c58dadced69c46bf`
- API contracts: `2afbaa2dcee0bf6abed7944f4e31d8b0749aeff604f1d5957b20d7ab897d885f`

The existing Web installer verified48 installed members and installed the same
source b87cc11c; wheel SHA
`ab8cb0ff850f9a76e9ee7fa9d4eb68479d48c9769594b316a9affc4e1407c1a7`.
Post-deployment HTTPS login page returned200 and HTTPS readiness reported API,
API readiness and observability ACTIVE. Web smoke and24 frontend/backend,
reference-start/default-off and release-integrity regressions passed. Actual
authenticated HTTPS login remains **PENDING**, not inferred from these checks.

API PID2047173, Web PID2049670 and QUERY PID2047176 are active. QUERY emitted actual
OWNER_READY at04:23:15UTC using its unchanged selected owner/configuration/provider;
INDEX PID130161/invocation053c5ab467ff4e29b4901cfabf037b4b is unchanged. The existing
QUERY provider's selected auth-code members are unchanged by this login release;
it did not require an invented source substitution. Numerical environments remain
untouched. Rollback record is
`/var/lib/eom-api/deployments/b87cc11c9a7a853c80877fdd39838b01292fb6e5.json`;
predecessor API19df and Webd265 artifacts remain available. No password recovery,
global session revocation or deliberate real-account login failure was performed.

## Actual authenticated HTTPS verification (recorded2026-10-24 04:47 UTC)

The authorized genuine HTTPS check against the deployed `eomai.duckdns.org` Studio
release passed. One genuine password entry created the test browser session with
`POST /studio/api/v1/session` returning201. The checker required its session cookie
to be Secure, HttpOnly, SameSite=Strict and scoped to `/studio`; an authenticated
`GET /studio/api/v1/session` returned200 with the same Operator ID, and
`GET /studio/` returned200. Only that newly created test session was logged out,
using its own cookie and CSRF token; `POST /studio/api/v1/logout` returned204.
The bounded actual completion evidence was:

```text
LOGIN_RELEASE_HTTPS_AUTHENTICATED_PASS session_read=200 studio=200 own_logout=204
```

This resolves the authenticated-HTTPS PENDING statements above. No password was
changed, no deliberate failed login was injected, and no global logout or other
session revocation was performed. Passwords, cookies, CSRF values and tokens are
not included in this evidence. The separate temporary client suite passed69
no-network mocked tests (47 baseline plus22 HTTPS-focused cases), including
one-prompt failure behavior, cookie/operator binding, own-session-only logout and
verified TLS connection cleanup; those synthetic tests are not substituted for
the actual successful check.

The public API and Web remain on login source
`b87cc11c9a7a853c80877fdd39838b01292fb6e5`. The operational QUERY provider's12 selected
code members remain unchanged; the login deployment did not repin its provider or
rewrite those members. The separately installed private benchmark SDK from
`e0d309e9…` is not a public API deployment and does not change the numerical worker
`d381e6bc480606a828898ebe2e9942dd8a143677`, native CPU/CUDA environments, model bytes
or numerical runtime pins.

This completes the permanent login recovery deployment and its actual HTTPS
verification only. It does not complete the separate six-launch embedding
comparison, original failure closure, coexistence/resource acceptance or any GPU
default activation; the production default remains CPU.

The Korean-first `COMPLETED / Login permanent recovery` milestone was delivered
at2026-10-24 04:47:23UTC: report
`devreport_ba42c71a05d248b2acced9fb11cd4d43`, SENT/HTTP200. It reports login completion
only and explicitly leaves the embedding comparison incomplete.
