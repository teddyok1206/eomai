# HWPX POC V0

## Scope

This POC builds one combined placeholder item and solution document from one approved Hancom-saved
reference template. It does not synthesize an OWPML document from scratch and does not claim Hancom
compatibility until a human completes the Windows open, edit, save, reopen, and semantic comparison
gate. Repository synthetic packages exercise parsers and transforms only.

The builder is a file-only process. It has no PostgreSQL, NAS, Codex, Docker, Git, or network
access. The eom-core adapter owns database records, local staging, result validation, artifact
commit, and finalization.

## Reference Import

```mermaid
flowchart LR
  H[Hancom-saved reference HWPX] --> Z[Bounded secure ZIP reader]
  Z --> X[Non-recovering safe XML parser]
  X --> A[Package analyzer]
  A --> B[Marker and object binding compiler]
  B --> M[Template-hash-bound binding manifest]
  A --> R[Analysis report]
  M --> C[Immutable template revision]
  R --> C
```

The importer preserves the reference `version.xml`, namespace profile, package entries, entry
order, compression methods, declarations, attributes, and unknown passive parts. Scripts, macros,
OLE, encryption, signatures, external links, executable content, and embedded packages are rejected.

For the initial content-team profile, the Hancom-saved `문항템플릿.hwpx` is staged read-only and a
file-only transformer creates the marker reference. It preserves the outer `1x1` problem container,
the `3x3` ㄱ/ㄴ/ㄷ view, and the bottom `9x4` management/solution table. The POC data surface is an
unmerged `2x3` table nested only inside the official `1x1` container. The generic `5x2` choice table
is intentionally excluded because it represents a different item surface without ㄱ/ㄴ/ㄷ statements.
This profile preparation does not weaken the general rule against arbitrary nested tables.

## Render And Validation

```mermaid
flowchart LR
  I[Strict item JSON] --> S[Fresh local workspace]
  T[Approved template revision] --> S
  M[Matching binding manifest] --> S
  P[Validated 800x500 PNG] --> S
  S --> R[eom-hwpx renderer]
  R --> Z[Reconstructed HWPX]
  Z --> V[Structural validator]
  Z --> E[Semantic extractor]
  I --> C[Semantic comparator]
  E --> C
  V --> J[result.json]
  C --> J
```

Text and table values replace only exact bound marker occurrences. The image replaces the one
binary identified by the reference PNG hash while retaining its package path and object
relationships. An equation is changed only at a location observed during import, using either the
stored marker or a unique anchor-bound equation source. The renderer never guesses an XPath.

## Core And Builder Boundary

```mermaid
flowchart TB
  subgraph CORE[eom-core environment]
    CLI[eomctl]
    DB[(PostgreSQL)]
    AD[HWPX execution adapter]
    AC[Existing artifact commit boundary]
    NAS[(Immutable NAS artifacts)]
    CLI --> AD
    AD --> DB
    AD --> AC --> NAS
  end
  subgraph BUILDER[eom-hwpx environment and Linux user]
    WS[Assigned workspace]
    B[eom-hwpx wheel]
    WS --> B --> WS
  end
  AD -->|staged files and transient unit| WS
  WS -->|result.json and output files| AD
```

```mermaid
flowchart LR
  A[eom-hwpx process] --> W[Assigned workspace]
  A -. blocked .-> N[/mnt/nas]
  A -. blocked .-> D[Docker socket]
  A -. blocked .-> C[Codex auth and worker homes]
  A -. blocked .-> G[Git checkout]
  A -. blocked .-> NET[Network]
```

## Artifact And Manual Gate

```mermaid
flowchart LR
  O[Generated HWPX and reports] --> ST[Local staging]
  ST --> H[SHA-256 verification]
  H --> TMP[NAS temporary revision]
  TMP --> R[Atomic immutable revision]
  R --> DB[(DB finalize)]
  R --> WIN[Windows Hancom open/edit/save]
  WIN --> RS[Re-saved HWPX inbox]
  RS --> CMP[Structural and semantic compare]
```

Linux structural and semantic success reaches `LINUX_POC_VALIDATED`. Only the recorded manual
Hancom gates can reach `HWPX_POC_V0_COMPLETE`.

## Persistence

```mermaid
erDiagram
  HWPX_TEMPLATES ||--o{ HWPX_TEMPLATE_REVISIONS : has
  HWPX_TEMPLATE_REVISIONS ||--o{ HWPX_BUILDS : renders
  HWPX_BUILDS ||--o{ HWPX_VALIDATION_RUNS : records
  ARTIFACTS ||--o{ ARTIFACT_REVISIONS : has
  HWPX_TEMPLATE_REVISIONS }o--|| ARTIFACT_REVISIONS : source
  HWPX_BUILDS }o--o| ARTIFACT_REVISIONS : output
  HWPX_VALIDATION_RUNS }o--o| ARTIFACT_REVISIONS : report
```

Logical IDs, revision IDs, package byte hashes, and semantic hashes remain distinct. An approved
template revision and every committed output revision are immutable. Build idempotency is enforced
by a unique normalized key.

Alembic revision `20260815_0003` adds `hwpx_templates`, `hwpx_template_revisions`, `hwpx_builds`,
and `hwpx_validation_runs`. HWPX actions also create ordinary platform jobs and immutable artifact
revisions, preserving the existing event and storage audit boundary.

## Preview And Determinism

Preview parts are not authoritative. A retained preview produces a stale-preview warning when it
cannot be safely regenerated on Linux. The renderer preserves entry order and compression method
but fixes ZIP timestamps to the DOS epoch. For the same template revision, canonical input, and
renderer version, output bytes and semantic hash are deterministic. Actual Hancom re-save behavior
will be recorded after the manual gate.

## Deferred Observability

The installed Observability Console is not rebuilt by this POC. A dedicated HWPX node requires a
future versioned observer contract and release: `OBSERVABILITY_HWPX_NODE_DEFERRED`.

## Dependencies

The dedicated environment contains only bounded format tooling and its test/build tools:

| Dependency | Reason |
| --- | --- |
| lxml 6.0.0 | Namespace-aware, explicitly hardened XML parsing and serialization |
| Pillow 11.3.0 | Deterministic PNG generation, signature decode, mode, and dimension checks |
| Pydantic 2.11.7 | Strict file contracts and internal immutable models |
| jsonschema 4.25.1 | Independent JSON Schema 2020-12 validation |
| Typer 0.16.0 | File-only builder CLI |
| pytest, Ruff, mypy, build | Isolated test, static-quality, and non-editable wheel gates |

No HWPX dependency is installed into system Python or added to eom-core. The contracts-only core
package uses dependencies already present in eom-core.
