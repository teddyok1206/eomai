# Codex update and compatibility maintenance

## Meaning

`control-plane codex-runtime check-update` performs a fixed, bounded official distribution
metadata read. It never runs `codex update`, installs packages, changes credentials, or
changes a production default. Network failure is UNKNOWN, not proof of being up to date.

`prepare-compatibility` pins an explicitly chosen matrix and the current account bindings.
`verify` performs real subscription-based native Codex calls through fixed isolated worker
units. This is not an external LLM API and not the existing NON_LIVE preset validation.
No item, HWPX, corpus or Content Pack is generated or activated.

## Operator sequence

1. Read the installed/source compatible release and exact current worker helper identity.
2. Run `eomctl control-plane codex-runtime check-update`. Review any candidate CLI update
   separately. There is no automatic update or implied installation approval.
3. Prepare a request with explicit repeated `--model`, `--effort`, and `--slot` selections,
   the installed `--source-commit`, and a private `--output-file`. The matrix is bounded to
   64 calls and expires after two hours. Select only the existing EOM effort enum; native
   max/ultra advertisement does not extend that enum. Run preparation as
   `eom-workflow-runner:eom`, not root or the interactive user. The new request must be an
   absolute canonical, single-link, runner-owned mode-0600 regular file outside Git.
4. During an approved idle maintenance window use the supported
   `scripts/workflow/run_codex_compatibility.sh COMMIT REQUEST_PATH` root wrapper. Its
   read-only preflight precedes any service stop. Busy work refuses the operation. It
   stops only the fixed Codex producer/auth services and restores the previously active
   set on success or failure. It never clears jobs/leases or stops an active model call.
   The pre-stop observation is not a reservation: new work arriving before service stop
   makes the subsequent locked DB/worker recheck refuse all probes and restore services.
   Use the approved quiet window; no new admission queue or global hold is created.
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
sudo /usr/sbin/runuser -u eom-workflow-runner -g eom -- \
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
