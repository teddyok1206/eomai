# Protected release-operator adapter

Status as of 2026-10-10 16:12 UTC: source and synthetic/source validation completed;
the protected operator adapter and compatible shared release were exercised for
`ad3ed8caf43f3a4ece5abce25b9b59801451803e`. Exact migration 0051, all seven closed
callbacks, API readiness and restoration of eight services passed. This is not
authenticated corpus, embedding, pair-comparison or human-quality acceptance.
This removable adapter covers the exact `20261010_0051` release migration, existing
runtime-role reconciliation and fixed API isolation verification. It is not a worker runtime, a new migration engine, or a
permission grant. Build-only release behavior remains unchanged.

## Required design (eleven points)

1. **Responsibility/boundary.** A reviewed, root-owned shell launcher verifies the
   interpreter before its first instruction. A small Python adapter then invokes only
   the existing Alembic and role-bootstrap callbacks. Neither the API service nor a
   worker gains database/NAS privileges through this adapter.
2. **Canonical source.** Independently reviewed Git commit/tree/archive bytes, the three
   release wheels, and their root-private source/package staging are authoritative.
   A developer checkout, ambient Python, a version string, and `PYTHONPATH` are not.
3. **Identity/revision.** The frozen local context keeps source commit, Git tree,
   archive hash, filesystem tree hashes and wheel hashes separate. This operation
   admits only migration `20261010_0051`, not an implicit future `head`.
4. **Pointers/checks.** Context, launcher, helper, interpreter and staged paths are
   exact absolute references. Check root-owned non-writable ancestors, regular
   single-link files, no escaping links, hashes, bounded JSON and file identities.
   Root-only admission creates a small receipt; its reuse is not an ACL token.
5. **Access patterns.** One sequential tree admission, keyed fixed callback lookup,
   three keyed wheel lookups and exact identity checks. No queue or registry exists.
6. **Structures/indexes.** Frozen dataclasses and a closed callback enum represent
   the local invocation. A sorted tree digest and sets protect deterministic ordering
   and duplicate rejection. No new database table/index is needed.
7. **Complexity/scale.** Initial admission is O(B+N), hashing immutable runtime/source
   bytes once. Subsequent callbacks perform O(N) ownership/mode/link checks plus
   bounded context/receipt and installed RECORD checks, not seven O(B) runtime hashes.
   This avoids repeating the measured approximately 79-second runtime fingerprint.
   GNU `find` checks UID/type/mode/link-count in one native traversal; regular
   members do not fork multiple `stat` processes. Only the much smaller symlink
   set needs individual containment resolution. The obvious process-count
   improvement is O(1+L) metadata processes instead of O(N) subprocesses, without
   a new cache or a weaker file predicate.
8. **Transaction/concurrency.** Alembic retains its existing PostgreSQL transaction.
   A release window must first classify/drain real jobs, commands and leases through
   supported owner projections. This adapter does not stop services or override BUSY.
   Role bootstrap retains its existing transaction/idempotency and secret ownership.
9. **Dependency/ownership.** `deploy_release.sh`/`migrate_release.sh` call the operator
   adapter. It calls unchanged public Alembic and reviewed bootstrap scripts. The
   protected interpreter is an explicit operator choice, not a mandatory embedding
   dependency. API/contract/platform wheel payloads are staged, not installed into
   the CPU prefix. Catalog/HWPX bootstrap source roots derive from their own script
   locations so an exact private copy cannot reopen `/home/eom/EOM` imports.
10. **Failures/retry.** Wrong UID, missing context/admission, changed identities,
    symlink/hash/schema drift or an unsupported callback fails closed before a
    privileged callback. No automatic retry/downgrade, secret copying, permission
    expansion or arbitrary command is supported. A failed migration is not a
    successful receipt. Historical records survive rollback.
11. **Simpler alternative.** The old root wrapper executes a developer-owned API
    interpreter and source `PYTHONPATH`, even for verification. Merely checking Git
    clean status or chowning old inodes does not close that execution boundary.
    Reusing an already admitted protected snapshot and exact private release stage
    is smaller than a new service/framework or a broad API-runtime ownership change.

## Closed invocation surface

Callbacks are `MIGRATION_VERIFY`, `MIGRATION_UPGRADE_0051`, `API_ROLE_BOOTSTRAP`,
`CATALOG_ROLE_RECONCILE`, `HWPX_ROLE_RECONCILE`, `PDF_RUNTIME_VERIFY`, and
`API_ISOLATION_VERIFY`.
Only `ADMIT` may hash/publish the operator receipt. No callback accepts a command,
actor, database URL, secret filename, migration revision or arbitrary source root.

The root operator first copies the reviewed launcher/helper into a protected
libexec directory, verifies their independently reviewed SHA values, stages the
exact release source and extracted wheels in a root-private directory, and admits
the protected interpreter/context once. The runtime snapshot must have been copied
onto fresh root-controlled inodes; changing ownership of developer-held inodes is
not snapshot publication. The adapter neither creates that runtime nor changes
global account/runtime ownership.

Install and standalone verify require explicit `EOM_RELEASE_OPERATOR_*` settings
for the protected launcher, interpreter prefix, context and their reviewed hashes.
Build-only does not inspect these settings. Credentials remain in the existing
fixed protected PostgreSQL/API/Catalog/HWPX configuration files; they are not put
in context, receipt, arguments, stdout, or the release record.

The exact local layout is:

```text
protected-libexec/
  release_operator_runtime.sh
  release_operator_runtime.py
  release_operator_context.schema.json
root-private-stage/
  operator-context.json
  operator-admission.json       # created once by ADMIT, O_EXCL, mode 0600
  source.tar                   # exact reviewed Git archive
  source/                      # exact extracted Git archive, no links
  dist/                        # exact platform / API-contracts / API wheels
  site-packages/               # raw extracted wheel bytes, including unchanged RECORD
```

Do not use `pip --target` for the small private wheel payload: its RECORD rewrite
and generated files would fail exact wheel/source closure. Wheels remain separate
from the protected interpreter. Admission compares source files to the exact tar
and package files to the exact wheel bytes; an independently hashed but different
extraction is not sufficient. Zero-byte Python/package files are valid data.

The explicit presentation options are `EOM_RELEASE_OPERATOR_LAUNCHER`,
`EOM_RELEASE_OPERATOR_RUNTIME_PREFIX`, `EOM_RELEASE_OPERATOR_RUNTIME_SHA256`,
`EOM_RELEASE_OPERATOR_CONTEXT`, `EOM_RELEASE_OPERATOR_CONTEXT_SHA256`,
`EOM_RELEASE_OPERATOR_LAUNCHER_SHA256`, and `EOM_RELEASE_OPERATOR_HELPER_SHA256`.
The context is `release-operator-context/1.0` and its reviewed JSON Schema is hash
bound into the helper. The body contains source commit/tree/archive/source-tree
hashes, interpreter prefix/tree hash and the three wheel filename/hash pins, never
secrets. The receipt contains exact context/interpreter file identities and hashes.

The reviewed, protected shell has the closed local invocation:

```text
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin TZ=UTC LANG=C.UTF-8
  /usr/bin/bash <protected-launcher> ADMIT <prefix> <runtime-sha> <context>
  <context-sha> <launcher-sha> <helper-sha> ADMIT <commit>
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin TZ=UTC LANG=C.UTF-8
  /usr/bin/bash <protected-launcher> EXECUTE <prefix> <runtime-sha> <context>
  <context-sha> <launcher-sha> <helper-sha> <fixed-callback> <commit>
```

Before invoking it as root, independently check the launcher bytes, ownership and
ancestors: its self-check alone cannot protect code already executed by Bash.
The normal unprivileged release library checks this before noninteractive sudo.
Use a clean environment before starting Bash; clearing `BASH_ENV` inside an
already executing script is too late to protect its first instruction.
The standalone migration wrapper rejects root before Git or sourced code. Run
that presentation preflight unprivileged; it makes one noninteractive sudo call
to the checked protected launcher. A root operator calls the protected launcher
directly. Copying only the wrapper would not protect its mutable checkout Git
configuration or sourced library. PostgreSQL file metadata and database owner
checks run only inside the protected root callback. Legacy Git preflight is not
an immutable source admission.

`PDF_RUNTIME_VERIFY` imports PyMuPDF only from the admitted protected interpreter.
It compares its `pymupdf` and native `_extra` member bytes to the existing fixed API
files using bounded nofollow FDs, root:root/single-link checks, name and parent
epoch checks. Text files remain exactly 0644. Only the fixed CPython 3.12 member
`lib/python3.12/site-packages/pymupdf/_extra.so` may be 0644 or the distribution's
standard non-writable 0755; other executable names, writable modes, aliases and
links remain rejected. The identical API/CPU native bytes are still checked; this
does not execute the API file or change installed ownership/modes. Existing
developer-owned API parents are not changed. This is a
data-only equivalence check, not privileged execution or ownership admission of
the legacy API interpreter.

`API_ISOLATION_VERIFY` closes the existing default deploy's last root invocation
of the developer-owned API Python entry point. It calls the already public
`eom_api.runtime_isolation_verifier.verify_runtime_isolation()` from the admitted
interpreter and exact staged API wheel. The unchanged verifier owns its pidfd,
fixed service/namespace identity, probe inventory and result validation. Its fixed
child enters the pinned mount namespace and drops UID, GID and capabilities with
`setpriv` before executing the API interpreter. The callback accepts no service,
PID, child command or probe override, does not read PostgreSQL configuration, and
does not treat the protected parent's UID as the service's access permission.
Any verifier exception or invalid return becomes a bounded fail-closed code.
This adds one closed callback, not a new verifier or supervisor. Installing the
legacy standalone shell remains compatible, but default deployment no longer
executes that shell's mutable interpreter as root.

Callbacks have a 180-second process limit (TERM, ten seconds before KILL). Fixed
libpq limits apply to every callback connection: connect 15 seconds, DDL lock five
seconds and statement 120 seconds. The unchanged native Alembic environment opens
its own connection, so `PGOPTIONS` propagates these nonpersistent settings rather
than pretending an unused Config connection attribute changes that environment.
A timeout prints `RELEASE_OPERATOR_TIMEOUT_STATE_UNKNOWN`: inspect the actual
supported state before any retry. Only bounded allowlisted operator error codes
are printed; native exception text, uncontrolled callback output and tracebacks
are not. The API bootstrap child uses clean environment and protected source cwd,
safe path/no user site/no bytecode, and a 150-second child limit. The existing
bootstrap replaces Bash with its DB Python using `exec`, preserving the PID;
there is no nested timeout process group. Its final status print moves unchanged
into Python. The outer timeout and child remain in the same process group, so a
long preflight cannot let a separate inner group outlive the outer deadline.
Timeout cannot be misreported as a normal rejection or silently retried.

## Deployment and rollback limits

The existing default deploy does not drain jobs before its in-place shared-package
replacement. Its preserve-runner option requires an already stopped runner and
installs a persistent hold; it is not automatic stop authorization. An operator
must preserve active job/lease evidence and establish the release window first.

Migration 0051 extends only the existing Workflow stage CHECK. It retains old
values/history, but PostgreSQL DDL needs an exclusive table lock and old installed
packages can fail exact-head readiness after the upgrade. Pin the compatible
release set and bound the transition window. Do not blindly downgrade once an
`INFERENCE_TRANSFER` history exists. Existing rollback policy retains the new
compatible schema/platform and withdraws the entry point when necessary.

No source test, admission receipt or migration PASS is evidence of live model
quality, human transfer quality, authenticated API activation or a complete release.

This patch does not assert that every historical privileged shell/metadata helper
in the release script has been redesigned. The root-private launcher is the new
boundary for these seven callbacks only; existing release checks and service
installation still need their established reviewed operator execution context.

## Recorded operational application

The 2026-10-10 release completed at 16:07:55 UTC for commit
`ad3ed8caf43f3a4ece5abce25b9b59801451803e`, Git tree
`a974e0754aaa8125cf8d481eda7d3c5cdc29b794`. Fresh admission used
`/var/lib/eom-release-operator-stage.ad3ed8ca-CJ7YAJ`, context SHA-256
`3cb2b8e14aa0d6b0e5074ffa77de68a5c8469193bc9e37870f812f9df3ee833d`, and source
snapshot SHA-256 `d805c8330f4ff368c6f47b44452d14d5359a49901abc782197c418bec100b4b7`.
The protected runtime retained its admitted byte-tree SHA-256
`d0dcd26e841ef583ead382b19269f559a3263a35ce809d34c6308bfe0399ed73`; no mutable API
interpreter was executed as root for these callbacks.

The normal deploy rebuilt the same source commit in a separate `BrDlZ9` build.
Its raw wheel SHA values therefore differ from the initially admitted `CJ7YAJ`
stage. Do not replace the admission context with installed-wheel hashes or claim
the two raw ZIP revisions are identical. The canonical installed set is recorded
in `/var/lib/eom-api/deployments/ad3ed8caf43f3a4ece5abce25b9b59801451803e.json`.
Full hashes, preserved prior admission/failure evidence and remaining gates are in
the [live acceptance record](../architecture/ITEM_INFERENCE_TRANSFER_LIVE_ACCEPTANCE.md).

The final observation at approximately 16:10–16:11 UTC had eight related services
active, enabled and with positive PIDs, plus the general-chat nonsecret runtime pin aligned to `ad3ed8ca`
and its dedicated slot READY. No actual `guiadmin` authentication/corpus read,
CPU forward, selected-pair submission or explicit comparison-control PREPARE/RELEASE
had yet been performed at this observation. These remain separate opt-in gates.
