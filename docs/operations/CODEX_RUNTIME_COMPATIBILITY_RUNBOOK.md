# Codex update and compatibility maintenance

## Meaning

`control-plane codex-runtime check-update` performs a fixed, bounded official distribution
metadata read. It never runs `codex update`, installs packages, changes credentials, or
changes a production default. Network failure is UNKNOWN, not proof of being up to date.

`prepare-compatibility` pins an explicitly chosen matrix and the current account bindings.
`verify` performs real subscription-based native Codex calls through fixed isolated worker
units. This is not an external LLM API and not the existing NON_LIVE preset validation.
No item, HWPX, corpus or Content Pack is generated or activated.

## Operator sequence: compatibility maintenance only

This sequence verifies the **already installed** CLI. It does not replace npm files or
admit the dedicated General Chat native app-server. For a shared CLI replacement, use
the coordinated upgrade sequence below; do not let this wrapper restore producers
between package replacement and all required admissions.

1. Read the installed/source compatible release and exact current worker helper identity.
2. Run `eomctl control-plane codex-runtime check-update`. Review any candidate CLI update
   separately. There is no automatic update or implied installation approval.
3. Prepare a request with explicit repeated `--model`, `--effort`, and `--slot` selections
   or an explicit `--matrix-file` (never both),
   the installed `--source-commit`, and a private `--output-file`. The matrix is bounded to
   64 calls and expires after two hours. Select only the existing EOM effort enum; native
   max/ultra advertisement does not extend that enum. Run preparation as
   `eom-workflow-runner:eom`, not root or the interactive user. The new request must be an
   absolute canonical, single-link, runner-owned mode-0600 regular file outside Git.
4. During an approved idle maintenance window use the supported
   `scripts/workflow/run_codex_compatibility.sh COMMIT REQUEST_PATH` root wrapper. Its
   read-only preflight precedes any service stop. Busy work refuses the operation. It
   stops only the fixed Codex producer/auth services and restores the previously active
   set on success or failure only after fixed-worker quiescence is confirmed. It never
   clears jobs/leases or force-stops an active model call.
   The pre-stop observation is not a reservation: new work arriving before service stop
   makes the subsequent locked DB/worker recheck refuse all probes and restore services.
   Use the approved quiet window; no new admission queue or global hold is created.
   After an interruption or timeout, a native unit may survive the owner's DB fence.
   `restoration-preflight` checks fixed-worker units before any producer restart, without
   requiring fresh bindings, request expiry or PostgreSQL availability. If evidence is
   busy/unavailable or the installed source differs, the wrapper withholds every restart
   and reports `CODEX_COMPATIBILITY_RESTORATION_UNCONFIRMED`. A partial stop failure can
   leave a partially stopped producer set. An operator must inspect actual unit states, the
   exact surviving unit and uncertain execution; do not force-stop or automatically retry
   it, bypass the preflight, or restart producers with unaccounted capacity.
5. Record actual calls, PASS/FAIL/NOT_RUN, runtime/contract pins, and the new canonical
   report Artifact/member pointer. First failure stops new calls within that request.
   The CLI `report_pointer` object is the exact existing `ArtifactMemberPointer` shape,
   including `artifact_id`, `artifact_revision_id`, full `eom://schemas/...` URI, member,
   media type and SHA. Use this object for the installer, not the separate human-readable
   `artifact` diagnostics or the whole CLI output.
6. If desired, use the narrow root policy installer with the exact committed report
   pointer and expected predecessor policy hash. It validates approved lifecycle,
   successful publication, schema/media/member/hash, exact runtime and freshness before
   atomically replacing the protected policy and keeping the predecessor for rollback.
   A local report JSON, model catalog, or NON_LIVE report is not an admission receipt.
7. Use supported OBSERVE commands to refresh account/native catalog/capability snapshots.
   Newly passed models then become selectable in administrator execution settings.
   Applying a different production default is still the existing draft → NON_LIVE
   validation → administrator apply workflow. Never mutate existing jobs' pins.

### Preparing with the fixed runner identity

Replace `COMMIT` with the exact installed lowercase 40-character source commit and choose
the explicitly approved model/effort matrix. The existing private runner directory is the
request materialization boundary; this creates a new file only, never overwrites a request.

```bash
sudo /usr/sbin/runuser -u eom-workflow-runner -- \
  /usr/bin/env -i HOME=/var/lib/eom-workflow-runner \
  USER=eom-workflow-runner LOGNAME=eom-workflow-runner TZ=UTC LANG=C.UTF-8 \
  PATH=/srv/eom/conda/envs/eom-api/bin:/usr/bin:/bin \
  EOM_POSTGRES_ENV=/etc/eom/secrets/postgres.env \
  /srv/eom/conda/envs/eom-api/bin/python -I -m eomctl.cli \
  control-plane codex-runtime prepare-compatibility \
  --source-commit COMMIT --model gpt-6.1-sol --effort medium --slot 01 --slot 02 \
  --output-file /var/lib/eom-workflow-runner/codex-compatibility-request.json
```

The model above is an example, not current admission proof or a production-default change.
No model executes during preparation. The root wrapper receives this exact request path
and commit; its fixed sanitized environment reads protected configuration through existing
adapters rather than sourcing any operator-provided environment file.
The runner account's primary group must remain `eom`. Both preparation and verification
reuse its existing supplementary groups, including the fixed worker-private groups; they
do not add account privileges. Do not add `-g eom` alone to `runuser`: it suppresses those
supplementary groups and workspace preparation then fails before native execution. The
root wrapper verifies the primary group before stopping any service.

### Explicit nonrectangular matrix

For different model/effort selections by slot, prepare an absolute runner-owned mode-0600,
single-link regular JSON matrix outside Git. It is bounded to 64 KiB and 64 unique triples;
only slot, model and the existing effort enum are allowed. For example, the shape is:

```json
{
  "schema_version": "codex-compatibility-matrix/1.0",
  "selections": [
    {"slot_id": "01", "model": "gpt-6.1-sol", "reasoning_effort": "medium"},
    {"slot_id": "02", "model": "gpt-6.1-sol", "reasoning_effort": "medium"},
    {"slot_id": "03", "model": "gpt-5.6-terra", "reasoning_effort": "high"}
  ]
}
```

These illustrative names are not admission evidence. Under the same fixed sanitized
runner identity shown above, replace the repeated selection flags with:

```text
control-plane codex-runtime prepare-compatibility
  --source-commit COMMIT
  --matrix-file /var/lib/eom-workflow-runner/codex-compatibility-matrix.json
  --output-file /var/lib/eom-workflow-runner/codex-compatibility-request-new.json
```

The server resolves exact current bindings/assignments/resource versions in one query;
never add those authority fields to the matrix. The same wrapper verifies the resulting
request. A reviewed 54-case recipe can use seven models × three selected efforts on 01/02
(42), then only baseline Terra × three efforts on 03–06 (12), rather than 126 calls across
all models/all six slots. Select the actual required default pairs and keep the budget
explicit. Do not execute both a 42-case request and a duplicate 54-case request by accident.

### V3 policy scope and future CLI updates

New root installations render policy V3. Each scoped entry pins binding, immutable
assignment, fixed slot and role. Slots 01/02 require the same model/effort to PASS on both;
slots 03–06 admit only their own actual PASS pairs. Failed, unexecuted or stale binding
cases do not become new scoped permissions. V1/V2 protected policy inputs remain readable
with their original meaning and schema bytes.

On an unchanged compatible runtime the existing global legacy Terra baseline may remain;
on a changed runtime it is dropped. A 01/02-only report is therefore not evidence that
registration (04), image (03), knowledge analysis (05) or PDF/support (06) is ready on a
new CLI. Include their required default pairs and review actual per-binding admission.
Never claim full workflow readiness from advertised models, a synthetic probe count, or
retained legacy globals. The separate General Chat app-server/account execution path is
not tested or admitted by this maintenance operation.

## Coordinated shared-CLI upgrade

This path is for an already enrolled dedicated chat account and the existing six fixed
worker accounts. It neither enrolls another account nor copies/rewrites authentication.
The version-neutral General Chat successor is described in
[the runtime evolution decision](../architecture/GENERAL_CHAT_CODEX_RUNTIME_EVOLUTION.md).
Source support, package installation, six-worker admission, and chat acceptance are
four distinct results. Installing a newer package is not itself compatibility PASS.

### 1. Select and preserve the exact predecessor

- Refresh `check-update`; explicitly choose a stable version from that observation.
  An earlier latest-version result is not an instruction to install whatever is latest
  when npm eventually runs. Use the reviewed exact version and official package source.
- Record source/installed component pins, migration, current CLI launcher target,
  launcher/native hashes, protected capability-policy SHA, protected chat-model
  configuration SHA, current chat release/model/protocol/RAG pins, and actual producer
  states. Check queue/claim/lease and physical native-unit quiescence, not health alone.
- Retain an exact, recoverable package tree and launcher symlink through the approved
  deployment backup boundary, with a manifest and integrity checks. Include native
  executable/resources, not just the JavaScript launcher. Use independent file bytes,
  not hard links: protected executable checks require single-link regular files.
  Record the protected configuration predecessors separately without exporting secrets.
  Never include Codex auth, tokens, worker homes, or credentials in a package backup.
- Install the reviewed compatible EOM source/wheels that support selected-runtime chat
  policy V5 before activating that policy. Do not assume the interactive checkout is
  the installed runtime. Confirm rollback includes the compatible previous release set,
  package and protected policy/configuration, not merely a Git commit.

### 2. Keep one explicit maintenance window

After read-only preflight and approved quiescence, retain the originally active states
and stop the existing five Codex producer/auth units:

```text
eom-general-chat.service
eom-general-chat-worker.service
eom-workflow-maintenance.service
eom-workflow-runner.service
eom-codex-auth-broker.service
```

Recheck physical native units and executable queue/claims before replacing npm files.
Stopping a producer is not proof that an already launched worker has exited. The API,
Catalog and HWPX services are not extra Codex producers and must not be gratuitously
stopped. Any new executable work, uncertain native operation, transitioning service,
or incomplete rollback material blocks package replacement; never clear its DB rows.

Install only the explicitly selected npm version using the reviewed root-owned layout,
fixed registry/configuration and bounded package operation. Preserve the supported
`/usr/local/bin/codex` launcher/native/resource layout and AppArmor/bwrap boundaries.
Do not run a blind self-update, accept an ambient npm prefix/configuration, or substitute
an alternate binary to bypass a failed layout check. The existing compatibility wrapper
is verify-only; it does not install or roll back a CLI package.

### 3. Prove and admit the new six-worker runtime

Under the stopped producer window, prepare a **new** request for the installed new
CLI/source and explicit approved matrix using the fixed runner identity. Include all
six slots' actual required defaults. The 54-case recipe above is one bounded choice,
not a compulsory full Cartesian product or proof for unexecuted pairs.

Run the existing root compatibility wrapper. Because these five units were already
stopped by the outer upgrade window, the wrapper records them as inactive and does
not restore them. Preserve the outer recorded states; do not rely on a second wrapper
to remember pre-upgrade states. First native failure stops remaining calls, and an
uncertain start is inspected through the same run/checkpoints rather than a new identity.

Resolve the committed report member and install capability-policy V3 through its
exact-predecessor-SHA installer. A report from the old CLI cannot admit this runtime.
Only after required current binding/default pairs are admitted and physical restoration
preflight passes may the originally active auth/Workflow producers be restored. Use
supported OBSERVE for all six current assignments and check the resulting admission
snapshots. No baseline model, preset, Content Pack, prompt or RAG policy is changed.

### 4. Select and verify the separate General Chat runtime

While **both chat services remain stopped**, use the existing chat runtime installer
with explicit `--pin-codex-runtime`. It captures the installed root-protected CLI's exact
version plus launcher and native SHA-256 into the existing model configuration; the
worker must not observe-and-adopt whichever CLI is present at startup. Pin mode preserves
the existing protected model, protocol 4 and released RAG policy; an explicitly supplied
different model/RAG selection is a conflict, not permission to change defaults.
Supply `--previous-model-config-sha256` for the guarded nonsecret configuration update.
Supply the stopped release predecessor only when advancing the installed EOM source.
For a compatible future CLI update on the same EOM release, the existing release pin
is validated and replayed unchanged; no artificial source commit is required.
Partial runtime pins, a different predecessor, protocol-3-with-new-pins, or a changed
executable epoch must fail closed before admission.

The three nonsecret keys in the root-owned model environment are:

```text
EOM_GENERAL_CHAT_CODEX_VERSION
EOM_GENERAL_CHAT_CODEX_LAUNCHER_SHA256
EOM_GENERAL_CHAT_CODEX_BINARY_SHA256
```

For an already installed compatible EOM source and unchanged release pin, the stage
command shape is:

```text
sudo /srv/eom/conda/envs/eom-api/bin/python -I scripts/chat/install_runtime.py
  stage COMMIT EXISTING_CHAT_MODEL
  --pin-codex-runtime
  --previous-model-config-sha256 sha256:EXACT_PROTECTED_PREDECESSOR_SHA256
```

Replace the placeholders with reviewed actual values; this is a command shape, not a
claim that any particular runtime is selected. A release advance adds the exact
`--previous-runtime-commit PREVIOUS_COMMIT`. Exact desired configuration replay is
no-write and must not replace auth/history or automatically launch a model.

Policy V5 and dispatch V5 record the explicit runtime. They map to the existing
protocol-4 request/reply/turn/tool/result path; they are **not** RPC V5 and do not expand
tools or permissions. Released policy/dispatch V1–V4 remain unchanged. Configuration
selection does not turn a legacy protocol-3 deployment into RAG-enabled protocol 4.
Installer readiness is a no-inference admission check, not answer acceptance.

Restore only the originally active chat pair after staging and readiness. Through the
existing authenticated application API/HTTPS path and actual user's permissions:

1. Confirm the separate `chat` slot is READY and submit one bounded plain-text turn.
2. Confirm that same submitted turn reaches COMPLETED with a committed result/history.
3. Submit a separate bounded internal-knowledge turn through the existing supported
   application path (automatic retrieval or an explicit grounded selection). Check
   actual official tool invocation and materialized,
   validated evidence/citations; merely mentioning RAG or having a READY slot is not
   evidence that retrieval succeeded. Empty/denied evidence is an explicit limitation,
   not this successful RAG canary.
4. Read the exact conversations/results again and confirm preserved historical lookup,
   operator authorization, policy/input/dispatch pins and new runtime provenance.

Use one stable idempotency key per submitted intent and the existing optimistic
resource version. On timeout poll/read the same conversation/turn; do not generate
another key and duplicate an uncertain submission. Count chat model submissions
separately from the six-worker matrix, read-only checks and HTTP replay. Do not create
an Item/HWPX or replay historical exam production as a CLI acceptance requirement.

### 5. Completion and rollback

Record exact installed CLI/source/hash pins, new canonical compatibility report, V3
policy SHA, six supported OBSERVE results, selected chat configuration/policy hash,
plain-text and actual-RAG canary outcomes, preserved defaults/history, model-call
counts, and final actual service states. Until both paths are accepted, report the
specific incomplete boundary rather than `CODEX_UPDATE=PASS`. Educational quality
remains NOT_EVALUATED by these synthetic/native checks.

On failure stop new submissions and retain failed/uncertain evidence. Keep the affected
capacity unavailable. Before replacing or restoring package files, confirm physical
native-process quiescence. Restore the exact protected predecessor package, launcher,
capability policy, chat configuration/release and compatible installed source as needed;
then repeat no-inference identity/readiness checks and restore only the previously
active units. Do not copy auth, modify failed history, or replace old result pointers.
If quiescence or predecessor integrity cannot be confirmed, withhold producer restarts
and report the specific operator action required.

For a future CLI that preserves this supported behavior, repeat discovery, explicit
version installation, exact runtime capture, new bounded proof and separate canaries.
Do not edit a source version constant or accept a semver range. Actual native protocol,
feature or tool incompatibility still requires a reviewed adapter/contract successor;
this mechanism is not an unconditional promise that every future CLI will work.

## Updates and failure handling

After a deliberate Codex CLI update, repeat the same workflow on the new exact runtime.
An old successful report cannot admit a changed version/binary/helper/contract. Account
reassignment likewise does not inherit another account's scoped execution evidence.
Existing global legacy pairs may be retained only on a compatible unchanged runtime;
untested new-runtime bindings remain unavailable until verified.

The existing fixed worker timeout is 1,800 seconds for ordinary slots, 7,200 seconds for
analysis/support slots. A short prompt is not a stricter timeout contract. Run cases
sequentially; do not bypass the host capacity fence or temporarily mark unknown models
AVAILABLE to obtain a production lease.

Exact run replay republishes/reuses conclusive checkpoints without new inference. A start
marker without a conclusive result is `CONTROL_COMPATIBILITY_EXECUTION_UNCERTAIN` and must
not be automatically retried. Preserve local execution evidence and inspect/reconcile the
exact unit rather than inventing a successful result or submitting the same intent under
a fresh identity because an HTTP/process timeout occurred.

Report only bounded milestone summaries to Slack, without prompts/results, credentials,
item content, or full logs. Compatibility PASS is a technical smoke result for requested
model/effort/account pins, not provider identity proof or educational-quality acceptance.

## Acceptance record

Implementation and runtime acceptance are recorded separately. Initial actual execution,
policy installation, model-selection projections, update discovery and service restoration
results belong here after they have occurred; source tests alone do not close those gates.
