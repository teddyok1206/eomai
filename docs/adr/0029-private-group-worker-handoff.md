# ADR 0029: Private-Group Worker Workspace Handoff

## Status

Accepted

## Decision

Use one Unix private group per `eom-cdx-N` worker. The unprivileged `eom` orchestrator is an
intentional supplementary member of those groups. Worker roots and job directories use setgid and
group-only access; staged inputs and finalized results are group-readable.

Normal execution may change only a path's group to an existing supplementary group. It must not
change UID, run as root, invoke `sudo`, or require `CAP_CHOWN`/`CAP_FOWNER`.

## Consequences

Input and output handoff works in both directions without a privileged runtime component. Worker
isolation remains per group. Login processes must be restarted after group membership changes.
Runtime bootstrap is a separate reviewed root phase for exact known directories, while all job
creation and execution remain unprivileged.
