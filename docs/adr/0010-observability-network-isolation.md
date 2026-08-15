# ADR 0010: Observability Network Isolation

Status: Accepted

## Context

The console exposes operational metadata and initially has one operator. Public or LAN exposure would
require TLS, broader identity design, and firewall review that are outside V0.

## Decision

- Bind only to `127.0.0.1:8780` and use an existing SSH forwarding path.
- Use a single scrypt-verified access token and signed, expiring HttpOnly session cookies.
- Keep secrets outside Git in `/etc/eom/secrets/observe.env`.
- Run as `eom-observe` without sudo, Docker, worker, or `eom` group membership.
- Apply systemd `InaccessiblePaths` to NAS, Docker, worker homes, root Codex auth, and the platform DB
  secret; keep repository and observer config read-only.
- Apply no UFW, router, port 8000, port 8765, reverse proxy, or TLS changes.

## Consequences

Access requires forwarding. Moving beyond loopback requires a separate ADR covering TLS, identity,
network policy, and operational ownership.
