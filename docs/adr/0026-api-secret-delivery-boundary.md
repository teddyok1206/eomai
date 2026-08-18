# ADR 0026: Application API Secret Delivery Boundary

## Status

Accepted

## Decision

Keep `/etc/eom/secrets` at `root:eom:0750`. systemd reads the Application API environment file and
injects the values before service credential application. Move non-secret configuration to
`/etc/eom-api/api.yaml`. Runtime doctor validates injected values and database behavior; a
privileged deployment verifier validates file metadata.

## Consequences

`eom-api` needs neither `eom` group membership nor traversal of the shared secret directory. The
runtime cannot independently stat its source environment file, which is intentional. Installation
must run the verifier after installing the reviewed unit and before starting the service.
