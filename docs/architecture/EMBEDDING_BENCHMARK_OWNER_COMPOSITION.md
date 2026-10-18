# Explicit six-launch benchmark owner composition

2026-10-18 UTC. Design before behavior; existing benchmark schema/recipe and
thresholds remain unchanged. No model run or operating activation is implied.
Continues the [existing execution composition](EMBEDDING_BENCHMARK_EXECUTION_COMPOSITION.md)
and [frozen device-comparison design](INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md).

1. Responsibility: assemble the existing Catalog fresh administrator/source/policy
   admission, fixed CPU/CUDA execution and Orchestrator series/Artifact owners.
   This is one operation-local application factory, not a new service or queue.
2. Canonical input is the closed BenchmarkOwnerRequest1.0 and selected immutable
   policy Artifact. Current authentication comes only from an actual supported
   Identity capture, never the request's audit ID, a stored row or root privileges.
3. Preserve benchmark/Job/execution/Artifact/revision/hash distinctions. The
   existing original Job key and six fixed ordinal reservations own replay.
4. Validate request/configuration/policy raw-versus-semantic hashes, actual capture
   provenance/operator and both typed native backend selections before composition.
   Actual current permission/ADMIN/Graph/source/provenance checks stay in admission.
5. Factory construction reads only OS account/process identity, not DB or Artifact
   bytes, and has no authentication, unit, model or publication side effect.
   Run uses existing indexed original-key and bounded six-launch
   history; constant-size composition, O(1) extra storage, no new index.
6. The actual fixed native owner UID/GID and no supplementary groups are required.
   No worker sudo, API credentials, root auth or model-supplied callable is added.
7. This supported composition uses the current native QUERY composition's
   900-second fresh-auth cap; the generic Identity fence contract is unchanged.
   A provided fence may be stricter, never looser. Do not renew authenticated_at or accept a fake
   capture to keep a long run alive. An expired gate remains explicit.
8. Publisher settings supply the installed owner source commit; root-controller
   release must match it. Reuse that publisher's exact engine/session factory and
   canonical artifact root. No ambient settings or shadow storage is introduced.
9. Catalog infrastructure composes existing public Identity/Orchestrator adapters;
   domain/schema code remains infrastructure-free. No dependency added.
10. Factory failure is content-free and before execution. Existing owner handles
    admission denial, capacity, original uncertain reservation and exact replay;
    no model retry/new identity or success reinterpretation is added.
11. Manually assembling disconnected adapters in an operator script was the simpler
    alternative but omitted the actual factory and made source/audit/runtime mixing
    easy. This function owns only composition, not another authorization rule.

The reviewed original-execution root controller must still serve its exact protected
stage before actual numerical work. This factory does not start privileged helpers,
install/select policies or provide that controller. The supported actual source
selection, live administrator capture, protected controller coordination, six real
measurements, comparison/default decision and actual rollback remain separate
operating gates. During the user's no-login interval, prepare/test these boundaries
without prompting or pretending an old session is fresh.

## Source verification — 2026-10-18 UTC

The explicit factory now connects the existing admission, fixed execution and
Artifact publisher using the original publisher's engine/session factory and
installed source commit. It introduces no schema, migration, dependency or queue.
The selected request is closed by the existing raw-value/schema/semantic codec;
policy member bytes and policy semantic identity remain distinct checks.

Related45 source suites: **1244 PASS /232.84s**, including17 new composition cases;
the earlier14 focused cases overlap and are not summed. Strict mypy1 production
module, Ruff/format2 and diff checks PASS. Local SQLite/actual adapter construction
is real; OS identity and issued Identity capture are synthetic test fixtures.
The real admission rejects that SQLite root before installed probes or Job writes.
An independent actual unprivileged process was rejected with the stable content-free
code before any model import or DB operation; this is negative process evidence,
not positive fixed-owner/live administrator acceptance.

Actual fresh-auth/source/policy admission, protected root-controller coordination,
six model runs and resource/cleanup assessment, paired QUERY/DOCUMENT device routing
and actual rollback remain OPEN. No operating DB, service, policy, protected owner,
numerical prefix, model, selector or default was changed. CPU remains selected.
Construction success is neither authentication nor runtime readiness. The user
requested no interactive login for24 hours from2026-10-18 00:13 UTC; stale capture
is not substituted for that missing live gate, and no additional login was requested.

## Canonical per-launch receipt closure — 2026-10-18 UTC

1. Responsibility: the existing launch publisher includes its typed
   `launch-receipt.json` in the same launch Artifact; final nine-gate assessment
   and original benchmark Job finalization remain separate.
2. Canonical source is the original validated native/root output and invocation,
   under the existing current `BenchmarkLaunchAuthorization` checks. A receipt
   or preselected publication identity grants no source or compute authority.
3. Preserve original benchmark Job, distinct publication Job, Artifact/revision
   and raw/content hashes. Preselect publication identities before serialization;
   keep CPU1's existing deterministic identity unchanged for its sealed reference.
4. Receipt pointers target that same Artifact's exact worker result, session and
   CPU1 reference/root completion. Its canonical serialized bytes are the same
   value returned for the original Job journal; there is no self-hash cycle.
5. Access is bounded ordered member assembly plus keyed name lookup. Add one
   small immutable JSON member, not another Job, registry or receipt table.
6. Work remains O(total launch output bytes); identity/receipt assembly is O(1).
   Native f32/token bytes are not rewritten, copied to another canonical Artifact
   or reinterpreted as new numerical/authorization evidence.
7. The existing file-set publisher retains its publication-key lock, immutable
   commit and exact replay semantics. Reauthorization still occurs before and
   after publication; late revocation retains original bytes and unresolved work.
8. Catalog's installed infrastructure adapter builds the receipt; only the
   existing Orchestrator file-set owner commits it to NAS. Worker output member
   names and all released schemas stay unchanged; no dependency is added.
9. New publications require exact preselected publication identities and one
   receipt member. A changed identity/hash or injected worker receipt fails.
   Unknown outcomes never allocate a replacement execution or retry a model.
10. Historical Artifacts are not upgraded or overwritten. Existing completed
    journal/read replay still accepts original Artifacts without the new member;
    trying to republish a different file set under an old key remains a conflict.
    A future finalizer must not fabricate a receipt pointer into such an Artifact.
11. Publishing six separate receipt Artifacts is the simpler disconnected option
    but adds six Jobs and storage boundaries. Extending the current launch owner
    reuses CPU1's established identity-before-serialization pattern instead.

## Read-only execution readiness — 2026-10-18 UTC

Status: preparation inventory only; no corpus materialization, tokenizer/model
execution, benchmark publication or six-launch acceptance was performed by this
inspection. A valid registered benchmark request, policy and input pointer were
not established from the inspected local preparation directories; this is not a
claim that the canonical database contains none.

- Normal INDEX and QUERY call `embedding_encoder_adapter.encode_incremental_batch`
  and `encode_reference_query_batch`, both through `backend.encode`. Their
  released result/shard contracts preserve input/space/vector hashes, **not**
  token IDs or `token_ids_sha256`. Do not reinterpret those vectors as a token
  witness. The benchmark's `encode_observed` produces the separate actual witness.
- The previous BGE experiment's `ExperimentTokenCoverage` preserves exact
  profile/view/text hash and measured token count, but not token-ID hashes.
  Reuse its validated original request/result for length-stratum selection only
  after matching model payload, tokenizer/prefix, recipe and rendered-text pins.
  Its retained receipt locator is
  `/var/lib/eom-workflow-runner/inference-transfer-experiments/owner-input-s9vek0xd/bge-successor-v1/{input,output}.json`;
  the existing reviewed `pair-completion-v11-bge-resume.py:retained_cpu` resolves
  the actual execution and registered result. This inspection did not dereference
  that private original corpus or establish current permission from its receipts.
- Select six currently eligible profiles, two per frozen length stratum, through
  `CatalogBenchmarkSourceAdmission` and the supported current Catalog snapshot.
  Keep the exact six source/report/Graph/policy revisions and canonical
  `experiment_view_text` values. Use the old coverage to avoid retokenizing520
  profiles, not to bypass fresh source authorization.
- For those6–18 DOCUMENT rows,2 QUERY rows, the8 public synthetic cases and the
  exact2048-token capacity text, a bounded future preparation operation can use
  the existing isolated CPU prefix `/opt/eom/conda/envs/eom-embedding-index-cpu`
  and `embedding_bundle_resolver.resolve_configured_embedding_bundle` to resolve
  the exact protected local tokenizer. `AutoTokenizer.from_pretrained` must use
  `local_files_only=True`, `trust_remote_code=False`, `use_fast=True`, the pinned
  purpose prefix and no truncation. Measure count and canonical unpadded
  `input_ids`/`token_type_ids` hash; load no `AutoModel` and run no forwards.
  The existing public `token_lengths` gives counts only; its backend constructor
  also loads the model. No existing tokenizer-only CLI was found in the inspected
  embedding scripts/adapters. This is one bounded preparation, not a new service.
- Publish the already released `BenchmarkStagedInputs` (`benchmark-inputs.json`)
  and `BenchmarkExecutionPolicy` (`policy.json`) through the existing
  `ControlFileSetPublisher`/`publish_benchmark_policy`. Then close the actual
  `BenchmarkOwnerRequest` and selected `BenchmarkOwnerConfiguration`; do not use
  the separately published INDEX policy as a benchmark policy.
- Prepare the exact protected controller before fresh login. The existing route
  is `embedding_benchmark_cuda_capture.serve_installed_root_benchmark_series`
  plus `embedding_benchmark_owner_composition.build_benchmark_execution_owner`
  and `BenchmarkExecutionOwner.run_launches`: CPU,CUDA,CUDA,CPU,CPU,CUDA.
  The four fixed `/etc/systemd/system/eom-embedding-benchmark-{cpu,cuda}@.{service,socket}`
  files exist and their hashes match the recorded installation. The prior actual
  root CUDA file-capture PASS remains valid evidence for its unchanged boundary;
  do not rerun that standalone capture merely to prepare this series.

Login must occur after these preparations. The real capture cap is900seconds;
six180-second per-launch bounds do not guarantee completion within that cap.
Expiry or an unresolved reservation requires the existing explicit reconciliation
boundary, not altered timestamps, a new execution identity or automatic rerun.
The completed-series numerical/timing readers and canonical new per-launch
receipts are implemented. Actual six runs, all nine genuinely evidenced owner
gates, original-Job finalization/publication, coherent device selection and actual
CPU rollback remain OPEN. Existing gate schema1.0 is sufficient; installation,
source tests and partial image/trainer proofs must not be promoted to those gates.
