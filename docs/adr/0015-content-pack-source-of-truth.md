# ADR 0015: Content Pack Source of Truth

## Status

Accepted

## Decision

Content policy is authored as validated text source and compiled into a deterministic `.eompack`.
The released bundle artifact revision, canonical manifest, and release row are runtime source of
truth. Git source, Intake working files, and activation pointers are not runtime identity.

Workers receive a rendered prompt artifact with release/profile/template hashes. They do not read
Git, Intake directories, PostgreSQL, or NAS.

## Consequences

Policy changes require a new semantic version. Bundle and source-tree hashes can be audited
independently. The restricted renderer is intentionally less expressive than Jinja and cannot run
code.
