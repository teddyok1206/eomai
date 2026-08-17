# Catalog Application Boundary

```mermaid
flowchart TB
  X[CLI / future API / future GUI] --> C[Typed Commands and Queries]
  C --> S[Catalog Application Services]
  S --> D[Domain Models and State Tables]
  S --> P[Persistence Ports]
  S --> A[Artifact Commit Port]
  P --> PG[(PostgreSQL)]
  A --> NAS[(Canonical Artifacts)]
  E[Future Excel Adapter] --> C
  H[Future HWPX Adapter] --> C
```

Interfaces may submit typed commands and render query DTOs. They do not implement lifecycle,
pointer, hash, idempotency, or transaction rules. Domain packages contain identifiers, values,
and transition tables and do not import infrastructure. Catalog services validate contracts,
resolve pinned revisions, and own transaction boundaries. PostgreSQL, NAS, filesystem, Codex,
and HWPX remain replaceable adapters.

Cross-component code must use public package APIs. Production packages must not import CLI
modules or another service's private modules. HTTP is intentionally absent in V0 and port 8765
remains reserved.
