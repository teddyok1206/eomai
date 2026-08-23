# Codex and Education Knowledge Control Plane Phase 0 Baseline

Status: Accepted implementation baseline; read-only inventory and design evidence only.

Observed: 2026-08-23 UTC

Repository baseline: `090045eae677a004072d56ddeb8430fa17dd214b`

## 1. Scope

This baseline records the existing Codex worker and platform boundary before implementing
[`CODEX_KNOWLEDGE_CONTROL_PLANE_IMPLEMENTATION_PLAN.md`](CODEX_KNOWLEDGE_CONTROL_PLANE_IMPLEMENTATION_PLAN.md).
It contains no credential contents, model invocation, database mutation, service restart, or worker
launch.

## 2. Host and Capacity Inventory

| Property | Observed value |
| --- | --- |
| host logical CPUs | 16 |
| physical memory | 31,945,644 KiB |
| swap | 8,388,604 KiB |
| configured worker identities | `eom-cdx-01` through `eom-cdx-05` |
| configured global Codex concurrency | 3 |
| configured GPU concurrency | 1 |
| fixed worker memory limit | 6 GiB each |
| fixed worker CPU quota | 200% each |
| fixed worker task limit | 256 each |
| worker UMask | `0007` |
| worker sandbox | `ProtectSystem=strict`, `ProtectHome=read-only`, `NoNewPrivileges=yes` |
| workflow runner | active, enabled, zero observed restarts |
| workflow runner limit | 2 GiB, 128 tasks |

The current five fixed templates resolve to these identities and roles:

| Slot | Linux identity | Role | GPU |
| --- | --- | --- | --- |
| 01 | `eom-cdx-01:eom-cdx-01` | authoring | no |
| 02 | `eom-cdx-02:eom-cdx-02` | review | no |
| 03 | `eom-cdx-03:eom-cdx-03` | image | yes |
| 04 | `eom-cdx-04:eom-cdx-04` | item management | no |
| 05 | `eom-cdx-05:eom-cdx-05` | support | no |

Every worker home is owner-private mode `0700`. Every slot workspace root is owned by its exact
worker identity/group with mode `2770`. The runner receives the five private groups but is denied
the worker credential-store subtrees by its systemd sandbox.

The installed `/etc/eom/worker-slots.yaml` is `root:eom:0640`, byte-identical to the reviewed
repository source at this baseline, and has SHA-256
`eb289d16f11eb23ebc2aaa79b465bd84d0d28dc0246dd45a89dcd424b1a3df08`.

## 3. Installed Codex and Execution Boundary

| Property | Observed value |
| --- | --- |
| Codex CLI | `codex-cli 0.147.0` |
| public executable | root-owned `/usr/local/bin/codex` symlink |
| resolved installation | root-owned system-wide Codex package |
| fixed worker executable | `/usr/local/libexec/eom-worker-exec`, `root:root:0755` |
| source/install executable parity | exact SHA match |
| executable SHA-256 | `3a98648520e7274591e1b3b36faba38d521bb6f467b526e6176949ba4d321d58` |

The fixed executable currently invokes:

```text
codex exec
  --sandbox read-only
  --ephemeral
  --ignore-user-config
  --skip-git-repo-check
  --color never
  --cd <validated job workspace>
  --output-schema <validated schema file>
  --output-last-message <validated result file>
  -
```

This correctly prevents persistent conversation reuse and ignores mutable user configuration while
retaining authentication from the fixed worker `CODEX_HOME`. It does not currently pass an exact
model or reasoning effort.

The installed CLI exposes `--model/-m` for non-interactive execution and `--config key=value`.
Official OpenAI documentation identifies `model_reasoning_effort` as the reasoning configuration
key and documents supported values as capability-dependent. Official documentation also makes
clear that higher effort costs more time/tokens and that advertised models are not proof of a
particular account's access. EOM will therefore distinguish published policy, observed capability,
and resolved execution evidence rather than build an allowlist from documentation alone:

- [Official Codex model guidance](https://learn.chatgpt.com/docs/models)
- [Official Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

No worker-account login status or model entitlement was asserted during this inventory. The
current operator shell cannot switch to a worker identity non-interactively, and reading a worker
credential store is forbidden. Phase 4 must add an exact-identity, sanitized observation boundary.

## 4. Current Execution and Queue Semantics

The Orchestrator currently:

1. validates and queues a Job;
2. selects the lowest enabled slot for its role from a five-entry in-memory registry;
3. writes the slot ID into the Job and transitions it to `CLAIMED`/`RUNNING`;
4. starts the fixed systemd unit synchronously;
5. validates and commits the resulting Artifact through the Orchestrator.

The workflow command queue uses PostgreSQL row locking with `SKIP LOCKED`. The configured global
and GPU concurrency integers are validated and observable, but no capacity-pool row, active lease,
or database uniqueness constraint currently enforces them on the Job claim path. Per-role
deterministic slot selection alone also does not prevent two concurrent callers from selecting the
same slot.

One collected historical slot-01 systemd instance was visible in a failed terminal state. No active
worker instance was observed. Historical unit state is evidence, not an active lease and not a
reason to reset or delete it in Phase 0.

## 5. Existing Canonical Data Boundaries

The implementation must extend these owners:

- `worker_slots` and `jobs` in the Orchestrator;
- immutable workflow definition, role protocol, Content Pack, result, and Artifact Revisions;
- `items`, immutable `item_revisions`, component pointers, and `item_provenance` in Catalog;
- existing `deliverables`, `deliverable_revisions`, mutable `usage_plans`, and immutable
  `usage_records`;
- Content Intake source files/batches and immutable source artifacts;
- Application API DTO/RBAC/idempotency and Scientific Studio BFF boundaries.

The implementation must not introduce a second worker registry, prompt system, Item Registry,
Usage Ledger, or canonical graph payload store.

## 6. Dominant Access Patterns

| Use case | Current structure | Required extension |
| --- | --- | --- |
| select a role worker | bounded list sorted by slot ID | indexed eligibility plus bounded deterministic selection |
| prevent duplicate active work | fixed identity only | partial unique active lease and locked capacity pool |
| choose model/effort | implicit CLI/account default | immutable preset and resolved execution plan |
| provide instructions/references | prompt/Content Pack inputs | pinned bundle manifests and local materialization |
| check authentication | deployment/operator knowledge | sanitized exact-identity health observation |
| traverse curriculum/items | source/item scans | snapshot-scoped adjacency, hierarchy closure, item element index |
| find Item usage | Usage Record indexes | exact revision reverse lookup plus derived graph projection |

## 7. Phase 0 Risk Register

| ID | Risk | Severity | Evidence | Owner phase / disposition |
| --- | --- | --- | --- | --- |
| P0-R1 | configured global/GPU limits are not claim-time constraints | high | no lease or active-slot uniqueness on execution path | Phases 2–4 |
| P0-R2 | model and effort are implicit account/CLI defaults | high | fixed command lacks `-m` and reasoning override | Phases 1–3 |
| P0-R3 | login/model readiness is not an authoritative pre-claim signal | high | readiness validates paths/config, not sanitized account capability | Phase 4 |
| P0-R4 | arbitrary future reference paths could bypass provenance | high | no immutable Reference Bundle contract yet | Phases 1–3 |
| P0-R5 | Graph ontology may duplicate Item/Usage canonical state | high | origin/product decisions were previously open | ADRs 0038–0039 and Phase 6 |
| P0-R6 | graph/source text can contain prompt injection | high | heterogeneous untrusted source corpus | Phases 7–10 |
| P0-R7 | account/model availability can change over time | medium | official catalog is not account entitlement | observation TTL and fail-closed resolver |
| P0-R8 | three concurrent 6 GiB caps may pressure other services | medium | 18 GiB summed cap on a 30 GiB host | Phase 4 benchmark, keep limit 3 |
| P0-R9 | legacy usage rows may be ambiguous | high | Excel identity/position conventions not yet typed | Phase 11 reviewed quarantine |
| P0-R10 | learner data could leak into a general graph | high | distribution boundary not yet implemented | ADR 0039; separate protected domain |

## 8. Phase 0 Exit Assessment

The current one-shot worker isolation and installed source/config provenance are suitable foundations.
The initial hardware policy remains five configured slots and three active Codex processes. The
control-plane gaps are now explicit and have bounded owner phases.

ADRs 0038 and 0039 resolve the minimum origin and product/usage identity decisions. The three first
graph queries and legacy mapping acceptance rules are recorded in
[`EDUCATION_GRAPH_V0_ACCEPTANCE_QUERIES.md`](EDUCATION_GRAPH_V0_ACCEPTANCE_QUERIES.md).

Phase 0 authorizes no migration or runtime change. Phase 1 may begin with immutable schema contracts
and tests.
