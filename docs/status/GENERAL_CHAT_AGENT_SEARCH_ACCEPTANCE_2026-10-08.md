# Conversational internal search operating acceptance

Observed: `2026-10-08T19:02:19.067978Z`.
`GENERAL_CHAT_AGENT_SEARCH_LIVE=PASS`.
Scope: `일반 → ChatGPT`, existing dedicated resident Codex slot, actor-authorized
read-only Item discovery/content and accepted solution-report summaries.
Task: `CHAT-READTOOLS-1` (implementation tag C06). This does not close the original
integration plan's C06 image/multimodal milestone.

## Compatible installed set

| Component | Immutable source / contract pin |
| --- | --- |
| API, Catalog, Orchestrator chat owner/worker | `7fb311fbfab683f9b3cf4cea123812e1f4e62591` |
| Compatible Web (unchanged presentation contract) | `6c765820d21f91dd1ef277219a894f25ddabac57` |
| DB migration | `20261008_0049`, unchanged |
| Additive turn input/result and owner/worker/dispatch | `general-chat-*/3.0` |
| Search/tool records | `eom://schemas/general-chat/agent-search/1.0` |
| Prompt revision | `general-chat-agent/1.0.0` |
| Native CLI / model | `0.160.0` / `gpt-6.1-sol`, enrollment unchanged |

Normal wheel build/install, installed RECORD, Catalog runtime roles, API isolation,
stopped-host chat owner/worker sandbox probes and READY activation passed.
Rollback record:
`/var/lib/eom-api/deployments/7fb311fbfab683f9b3cf4cea123812e1f4e62591.json`.
API, Web, Catalog application runner, workflow runner/maintenance, HWPX manager
and both chat units were active after acceptance. Existing slots01–06 are unchanged.
No DB migration, queue replacement, new OS identity, privilege grant or dependency.

## Product meaning and protected boundaries

- Codex can choose concept, recent-Item or exact-exam discovery, read offered
  immutable revisions and answer with verified citations without user attachment.
  Existing manual search/attachment remains supported.
- Per turn: at most four searches, six cards per search, one read, three distinct
  Items and nine content sources. Search uses existing indexed queries, not a
  corpus dump or unrestricted model DB query.
- The worker requests exactly `search_eom_items` / `read_eom_items` on the existing
  owner-initiated authenticated connection. It has no DB, Catalog socket or NAS
  write access. Only the Orchestrator publishes validated tool evidence.
- Source permission, lifecycle, exact revision/hash, snapshot and lineage are
  checked through existing resolution. Final admission resolves canonical tool
  records and verifies answer citations; history/follow-up reauthorize access.
- Reads never substitute an implicit latest revision. Approval, Graph membership,
  accepted report status, model proposal and timestamped observation remain distinct.
- No production, review, approval, account, deployment, shell, arbitrary network,
  image-pixel inspection, PDF inspection or new textbook privileges are exposed.
  Receipt integrity is not educational-quality acceptance.

## Verification

| Gate | Result |
| --- | --- |
| Final protocol/backend/API/Web/dependency source suite | 623 PASS |
| Disposable chat persistence, including V3 canonical tool records and revocation | 49 PASS |
| Disposable shared search/query-plan/limited-role suite | 23 PASS |
| Separate fresh disposable chat runtime-role suite | 12 PASS |
| Ruff / formatter on 32 changed Python files | PASS |
| Mypy on 27 changed production/generator files | PASS |
| Schema mirror regeneration check | PASS; released bytes unchanged |
| Actual pinned native strict-config parser, empty home/closed stdin | PASS; no auth/init/inference |
| Installed wheel RECORD/API runtime isolation | PASS |
| Owner/worker OS isolation | PASS; no inference |
| Actual HTTPS, no-attachment SEARCH→READ answers | PASS, two turns |
| Accepted Graph-linked solution report and S1/S2 citations | PASS |
| Exact-Item/report follow-up without new search | PASS, one turn |
| Citation button to exact-revision Preview | PASS |
| Same-intent HTTP replay | PASS; no duplicate turn or model generation |
| History reload / browser page errors | PASS / zero |
| Canonical postflight / original 21 terminal receipts | PASS / unchanged |
| Task-owned disposable DB cleanup | PASS, two databases; production data preserved |

Suites overlap; source counts are not summed into a larger claimed suite.
The existing Starlette/httpx test-client deprecation warning remains.
After activation, only the developer schema generator received type annotations;
the mirror check proves no schema bytes changed. That non-runtime tooling change
does not replace the installed source pin above.

## Actual execution evidence

The first two turns had zero prepared sources and no manual selection. Canonical
receipts independently prove that tools executed, not just that source cards appeared.

| Purpose | Turn | Actual tool outcomes / sources |
| --- | --- | --- |
| Recent Item content, concept/answer/approval | `chatturn_4185c715a9073f81f7e0f33d2dcc59d7` | SEARCH EMPTY → SEARCH SUCCEEDED → READ SUCCEEDED; `REGISTRY_DIRECT`, S1 |
| Internal electromagnetic past exam + accepted report | `chatturn_648006358b06ed48e4fa66612102e87c` | SEARCH SUCCEEDED → READ SUCCEEDED; `REGISTRY_DIRECT` + `SOLUTION_REPORT`, S1/S2 |
| Same Item's source-supported transformation suggestion | `chatturn_daa40532d1121f200dcb419c682f652d` | No new tools; same exact selection/report and S1/S2 |

The first EMPTY generated-source filter was honestly empty; subsequent existing
recent-Item discovery found a source-unclassified Item. No source profile was
invented or repaired to turn the empty result into success.

| Output Artifact | Immutable revision |
| --- | --- |
| `artifact_e6ed63397eec43318e39516d911de396` | `rev_07bfbec1e198458a95b2de81adbef928` |
| `artifact_924fc25f00c748379e2977b883d8f0e3` | `rev_7cba562fb80d41fbbdf5503e7204c3e2` |
| `artifact_e450812ce7654f989fff163640138dec` | `rev_b0d84cbdb7e54cb089f3b551f53b3740` |

Exact pinned Graph: `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9` /
`sha256:da76258a650dcb66c3303f579ec1502215bda6cb75f05808414809d7076bf645`.
Last result SHA:
`sha256:b00b782dbf76913671435b272639abe53e4c6d8099d03cb43b4dc6fe3cdc6648`.
Final active chat turns: zero. Canonical tool pointers, full request/result hashes
and byte counts remain in Artifact manifests and the sanitized postflight evidence,
not copied as item content into Git.

## Actual-use discovery and honest execution accounting

The initial C06 turn `chatturn_4eebcdb6558efa2020fc5f16fccd04e5` completed with
zero tools and insufficient evidence. It is preserved as non-acceptance, not
relabeled as a successful search or rewritten after the fix.
The installed model metadata requests `code_mode_only` independently of disabling
the Code Mode feature, hiding flat tools by default. The pinned CLI's supported
setting now exposes only the direct `functions` namespace:

```toml
features.code_mode = { enabled = false, direct_only_tool_namespaces = ["functions"] }
```

The Code Mode host, shell and other native capabilities remain disabled. Auth and
model metadata were not edited. An intermediate raw `code_mode.*` TOML override
was rejected by the real strict startup parser, withdrawn and corrected before
any model execution or new turn. The full launcher now has a no-inference actual
CLI parser regression test, in addition to protocol mocks.

This C06 task made four explicit model submissions: one retained non-acceptance
and three completed acceptance turns. One HTTP replay generated no additional
model turn. Startup/config/isolation checks generated none. No GPU, HWPX,
single-item authoring or 25-item production was submitted.

The stopped worker's service-manager failed latch from rejected startup was
cleared only for that unit before the stopped-host isolation probe. DB execution
states, failure history, canonical artifacts and journal were not rewritten.

## Maintenance / evidence

See [design and supported native routing](../architecture/GENERAL_CHAT_AGENT_SEARCH_DESIGN.md)
and [previous manual-attachment acceptance](GENERAL_CHAT_REPRESENTATIVE_ACCEPTANCE_2026-10-08.md).
The two task-owned disposable test DBs were removed using the guarded cleanup
command. Other test workspaces, production Items, Graphs and rollback wheels remain.
Sanitized operator proof was archived through the existing Orchestrator publisher:

- Artifact: `artifact_5d5d229e54a143c6832bd3636bf45941`.
- Revision: `rev_8d30f85affff4ccd844598f81487d62a`.
- Manifest SHA: `sha256:f67db9add944a34b573ceb4a68cd3df186cf666cce13258b9accb49d39d75e0f`.
- Primary member: `proof/postflight-final.json` /
  `sha256:3899219fa447288cf24cae6ecb333ca02fd7c2c38df8488d73c21915217e8d05`.
- 22 bounded sanitized log/metadata/screenshot members; archival submitted zero model calls.
