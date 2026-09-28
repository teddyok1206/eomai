# ADR 0140: Workflow runner release identity

## Status

Accepted.

## Context and responsibility

The Workflow runner consumes the shared platform wheel and coordinates visual-reference discovery
for hybrid image requests. Reference commands must pin the exact installed source release. The
runner previously accepted an optional `EOM_RUNTIME_SOURCE_COMMIT`; a current Content Pack could
therefore reach the image step while the live unit omitted the value and fail with
`VISUAL_REFERENCE_ROUTE_UNAVAILABLE`.

The API/platform release owns the shared runner unit and its release identity. The image-provider
deployment owns provider identities, model wheels, provider/reference units, polkit, and the active
provider binding. It does not overwrite the shared runner unit.

## Canonical source and identity

The canonical identity is the immutable Git commit selected by `scripts/api/deploy_release.sh`
before building the three reviewed wheels. The deployment materializes one root-owned file:

```text
/etc/eom/workflow-runtime.env
EOM_RUNTIME_SOURCE_COMMIT=<40 lowercase hexadecimal commit>
```

The value is not a filesystem identity and does not replace wheel RECORD hashes or release
receipts. It is the pinned source revision passed into visual-reference commands. The systemd unit
requires this file and exposes it only to the Workflow runner.

## Access patterns and data structures

The runner performs one keyed environment lookup at process construction and reuses the frozen
`Settings` value for every command. This is O(1) time and constant space. No DB row, cache, queue,
or mutable latest-pointer is introduced. The existing indexed command queue and lease model remain
unchanged.

## Transaction and deployment boundary

While the existing workflow-runner deployment hold fences execution, the platform installer:

1. writes the exact commit to a staged root-owned regular file;
2. atomically renames it to the fixed runtime identity path;
3. installs the canonical runner unit from the same clean commit;
4. reloads systemd and restarts the reviewed long-lived consumers; and
5. verifies file metadata, exact content, unit bytes, and service health.

The standalone runner installer follows the same identity rule. Existing Workflow, Item, Artifact,
and evidence revisions remain immutable.

## Failure, retry, and rollback

Missing, malformed, symlinked, permission-drifted, or commit-mismatched identity files fail closed
before the runner is declared installed. Re-running the same release is idempotent. Rollback
reinstalls the prior reviewed wheels, unit, and the prior commit identity through the same release
boundary. No workflow row or failed history is rewritten.

## Alternatives

Deriving the commit from the repository checkout is invalid because the runner cannot read the
repository and checkout state is not installed identity. Importing Application API build metadata
from the orchestrator would reverse the dependency direction. Making the field optional preserves
the observed late failure. A small root-owned immutable environment file is the simplest explicit
boundary.
