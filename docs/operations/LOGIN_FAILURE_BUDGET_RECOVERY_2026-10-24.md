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
