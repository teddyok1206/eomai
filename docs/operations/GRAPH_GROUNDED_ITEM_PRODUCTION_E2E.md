# Graph-Grounded Single-Item Production E2E Runbook

Status: reviewed one-shot rollout and acceptance procedure
Owner: EOM operator
Architecture: `docs/architecture/GRAPH_GROUNDED_ITEM_PRODUCTION_E2E_V1.md`

## Safety boundary

This runbook installs the reviewed source, activates the compatible generated-item Content Pack,
publishes the reviewed `standard-item` V3 policy, creates the first immutable
`knowledge-grounded-item` preset revision when absent, and only after deployment checks pass creates
one disposable item workflow and one HWPX build. It does not alter the
published textbook Graph, historical presets/plans, textbook-analysis batches, canonical legacy
items, HWPX templates, worker credentials, port 8000, or EOMIS.

Persist a mode-0700 acceptance directory. Create one mode-0600 workflow authorization marker at
the workflow submission boundary and one HWPX authorization marker at the HWPX submission
boundary. Each operation uses one unique idempotency key and has no automatic retry. A lost HTTP
response may be recovered only by replaying the same key and byte-identical request.

## A. Immutable preflight

1. Require the reviewed Git commit, clean tree, matching installed API/GUI source provenance, and
   active/enabled API, Catalog application runner, workflow runner, HWPX Manager/application
   runner, GUI, Observability, Caddy, and PostgreSQL services.
2. Require Application API, Observability, and Studio to remain bound to loopback and require the
   public Studio path to pass only through Caddy. Do not change port 8000.
3. Read and record the current access-policy revision/hash, active `generated-knowledge-item`
   release/hash, workflow definition 1.5.0/hash, the current released `standard-item` policy, any
   existing `knowledge-grounded-item` logical preset, and production corpus/snapshot pointers.
4. Require `integrated-science-textbooks` to be ACTIVE with one PUBLISHED current snapshot whose
   capability reports 43 curriculum units and 119 closure rows against the pinned outline hash.
5. If `knowledge-grounded-item` exists, require no unresolved DRAFT revision and require any current
   released revision to match the reviewed policy before reusing it. If it is absent, create only
   the reviewed first revision. Do not overwrite or deprecate any historical revision.

## B. Source and isolated-database gates

Run repository-owned Ruff, formatter, strict mypy, full non-live platform/API/Web suites, OpenAPI
determinism and breaking checks, shell syntax, repository boundary/secret scan, API/Web release
builds, and the disposable PostgreSQL integration harness. No live Codex or HWPX invocation belongs
to these gates.

## C. Compatible Content Pack and presets

Import, release, and activate the reviewed `generated-knowledge-item@1.3.0` Content Pack before new
V2 item requests are accepted. The pack activation changes only the current release used by future
workflow starts; historical workflows remain pinned to their original releases.

Publish the reviewed `standard-item` V3 policy from
`config/control-plane/standard-item-v3/bootstrap.yaml`. Its manifest uses
`standard-control-bootstrap/3.0`, pins `workflow-role/1.12.0`, and writes instruction bundle
revision number 3 so the SVG-first instructions never collide with V1/V2 immutable bundle
history.

Create one V2 revision under the separate `knowledge-grounded-item` logical preset by copying the
current released `standard-item` V3 executable policy exactly and adding only the reviewed retrieval
boundary:

```text
retrieval_policy.allowed_corpus_keys = ["integrated-science-textbooks"]
retrieval_policy.allowed_query_kinds = ["ITEM_PREPARATION"]
retrieval_policy.allowed_source_classes = ["APPROVED_ITEM", "TEXTBOOK"]
retrieval_policy.access_policy_revision_id/hash = reviewed production access policy
retrieval_policy.maximum_budget = reviewed production cap
role evidence_access = EVIDENCE_CONTEXT for authoring/image/review, NONE for item_management
```

Require the access-policy revision/hash, query kinds, source classes, maximum budget, capacity
policy, role policies, evidence-access map, model/effort, instruction/reference bundle pointers,
timeouts, sandbox/network settings, and compatible role protocol to remain byte-equivalent to the
reviewed standard V3 base except for the explicit retrieval and evidence-access fields. Record the
base revision ID/hash, target DRAFT ID, and computed target policy hash.

Publish a bounded non-live evaluation Artifact that identifies the exact target DRAFT and policy
hash and records only gate counts and stable summary codes. Attach it through the existing preset
evaluation service, then release the DRAFT. Require the logical current pointer to select the new
RELEASED revision and re-resolve it through `current_knowledge_backed_preset`. The old current
revision remains immutable and readable.

If the current standard V3 policy differs from the reviewed preflight or any extra field changes,
stop before creating a DRAFT. If a matching `knowledge-grounded-item` policy is already released,
verify and reuse that revision rather than creating a duplicate.

## D. Minimal deployment

1. Install only the reviewed API/platform/contracts release through `scripts/api/deploy_release.sh`.
2. Restart only the services importing changed code: Application API and Catalog application
   runner. The canonical API installer owns its API restart.
3. Install the reviewed Web wheel and restart only Scientific Studio.
4. Do not restart workers, HWPX services, Observability, Caddy, PostgreSQL, or port 8000.
5. Verify installed imports originate in the pinned environments, API and GUI build information
   equals the reviewed commit, and all services remain active/enabled.

## E. One fresh Graph-grounded item

Through Scientific Studio/Application API, submit one new disposable
`generic-item-development@1.5.0` request using:

- the active `generated-knowledge-item` pack;
- the released `knowledge-grounded-item` preset;
- one reviewed large or middle curriculum unit;
- normalized natural-language guidance and exact guidance/spec hashes;
- `ITEM_PREPARATION`, the server-derived production corpus and curriculum root, no topic keys;
- the fixed required item elements and approved source classes; and
- one fresh idempotency key.

Before worker execution, require the resolved plan to pin the new preset revision, the published
full Graph Snapshot, one new bounded Evidence Bundle, access policy, Content Pack release, workflow
definition, and all hashes. Then allow the existing orchestrator to run authoring, image, review,
human approval, and registration. No worker talks to another worker or accesses DB/NAS.

Require terminal `COMPLETED`, one approved current Item Revision, pointer-only provenance visible in
Studio, and automatic population of the preview and HWPX revision inputs. Preserve a failure as
evidence and stop without a fresh submission key.

## F. One HWPX build and secure download

After the Item Revision is current and APPROVED, submit exactly one `eom-template` HWPX build with a
fresh key. Require `SUCCEEDED`, validation `PASS`, renderer version 1.0.0, one native equation, one
content native table, four total native tables in the internal receipt, output Artifact/Revision
pointers, and output SHA-256. Download exactly once through Application API -> private Manager Unix
socket, require the HWPX media type and safe disposition, and require downloaded SHA-256 to equal
the output SHA-256. Never use direct NAS, direct builder, direct Node, or direct Kordoc execution.

## G. Post-check and rollback

Verify the exact workflow, Item Revision, HWPX build, DB Explorer projection, recent-item/HWPX GUI
history, and pointer-only Graph provenance. Require the published Graph, textbook analyses,
historical workflows/items/builds/presets, services, ports, Caddy, EOMIS, and Git state to remain
unchanged except for the explicitly created new immutable records and deployed source revision.

On code failure, reinstall the prior reviewed API/GUI wheels. On preset failure, restore selection
through a reviewed current-pointer operation; never delete or edit revisions. On workflow/HWPX
failure, preserve all evidence and do not retry automatically.
