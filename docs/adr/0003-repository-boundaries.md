# ADR 0003: Repository Boundaries

Status: Accepted

## Context

EOMIS exists as a separate legacy project. The new EOM platform must not inherit accidental code, Git history, credentials, or runtime assumptions from it.

## Decision

- EOMIS and EOM are separate repositories.
- EOMIS is not modified by EOM bootstrap or future EOM development.
- EOM Git history is not connected to EOMIS.
- EOMIS files are not directly imported or copied into EOM.
- Future integration must use explicit adapters, manifests, or documented migration inputs.
- Raw audit reports and command logs are not copied into EOM Git history.

## Consequences

Any compatibility layer must be deliberately designed and reviewed. EOM starts with its own protocol, schemas, and storage rules.
