# Reviewed host baseline successor — 2026-10-21 UTC

User approved requalification for the updated OS, preserving all predecessor evidence.
This is the existing native-runtime installation/admission path, not a new model,
search service, queue, source permission or general dependency-update mechanism.

## Design and boundary

1. **Owner.** The fixed host closure owns reviewed library bytes; the existing host
   snapshot and CPU/CUDA installation owners select, audit and seal successors.
   Identity/Catalog source authority and Orchestrator artifact ownership stay intact.
2. **Canonical source.** Current protected OS files are the library source. Existing
   immutable archives, model, tokenizer and numerical wheels remain canonical. Do
   not downgrade the OS or create a second library copy just to pass an old receipt.
3. **Identity.** Keep the original host baseline SHA and file table immutable. Add
   one separately named, content-addressed reviewed baseline with only the known
   liblzma change. New host snapshot, native configuration, inventory and admission
   receipt use new immutable revisions. Neither an ID nor a source commit is a hash.
4. **Pointers.** Resolve the exact baseline hash to one of two compiled reviewed
   file tables. Resolve the host snapshot/config/receipt through existing bounded
   no-follow readers, schema/raw/semantic hashes, ownership, ACL, lifecycle and
   actual mount/epoch checks. Unknown baselines fail; there is no current/latest
   host fallback and no caller-supplied library allowlist.
5. **Access.** Baseline lookup is fixed key lookup; native resolution is exact
   revision lookup; closure is bounded ordered file/dependency traversal. No corpus
   scan or Item reads belong in host requalification.
6. **Structures.** Use two immutable file tuples and a closed lookup, plus existing
   snapshot/capture values and installation manifests. No new persistent aggregate,
   DB migration/index, runtime flag or dependency is needed.
7. **Cost.** Baseline selection O(1), seed derivation O(23), ordinary host capture
   retains its existing streamed-byte/ELF graph cost. Reuse held file epochs; do
   not repeat a full ML-prefix audit for each text or search request.
8. **Concurrency.** Inspect/drain affected native work and hold the existing profile
   publication lock before a prefix successor. Preserve the prior prefix/receipts.
   Existing readonly pre-exec cache mounts remain required; a library or namespace
   change during capture denies admission. Do not reset/retry uncertain work.
9. **Dependency direction.** The stdlib host/capture adapters share one implementation
   with the bootstrap; contracts contain values only. CPU/CUDA factories and owners
   use their existing public admission interfaces, not private database mutations.
10. **Failure/replay.** Old baseline/receipt still rejects new liblzma. New baseline
    still requires exact bytes, ELF, aliases, symbol versions and closure. Partial
    installation/audit evidence is retained and not rewritten. Activation is a
    separate supported selection after actual no-forward admission succeeds.
11. **Simpler alternative.** Replacing the original SHA would reinterpret history;
    accepting arbitrary current hashes would remove the boundary. A new schema or
    generic updater is unnecessary because the existing snapshot already carries
    a content-addressed baseline identity and native receipts pin its exact seed.

## Exact reviewed difference

| Member | Predecessor SHA-256 | Successor SHA-256 | Size |
| --- | --- | --- | ---: |
| `/usr/lib/x86_64-linux-gnu/liblzma.so.5.4.5` | `696e868dd0700a19a6d65fc01608ec2d70d3cb91f65710e89180cd2e688f30cb` | `26b37d25f7ca2a2d348de8ecabacda12e921cd933b21fa069a179760db77219d` | 202904 |

The 2026-10-21 06:18:18 UTC package update changed liblzma5 from
`5.6.1+really5.4.5-1ubuntu0.3` to `…0.4`. All other 22 fixed host members,
11 aliases and closed search routes were independently checked. The current
global cache differs from the oldest source seed but equals the admitted CPU
cache snapshot; the CUDA cache and its seven copied driver libraries are unchanged.
These observations select a candidate, not native admission.

## Existing contract meanings remain unchanged

Snapshot1.0 `baseline_host_seed_sha256` is a SHA identity, not a schema enum fixed
to the predecessor. Its unchanged format can name a new reviewed baseline. The
resolver must select that exact table, derive the cache-substituted target seed
from it and independently match the accepted inventory/receipt. Original snapshots
continue to select only the original table. Old readers reject the new baseline;
installation/release alignment must ensure they are not selected with new controls.

Keep `capture_protected_embedding_host` and the old default seed entry point
strictly on the predecessor. New named reviewed-baseline functions serve only
explicit snapshot selection. CPU and CUDA base capture both use that selection;
CUDA must not silently rebuild its base with the old table.

The CUDA publication adapter also passes the already-resolved base snapshot to
its existing cache builder. Its closed SONAME routes verify against that exact
reviewed baseline, including the snapshot's cache metadata, before starting
ldconfig. Retained base epochs are checked again after the cache unit; unknown
baselines or changed source bytes cannot become a published host revision. This
is a correction inside the current publication owner, not a new update API.

No benchmark request change is required. `BenchmarkRuntime` separates numerical
identity from `NativeEmbeddingBackendPins`. Keep the exact model/bundle/proof,
numerical fingerprint, family/spaces, recipe, source/Graph/policy, rows and 29 token
witnesses. Only independently verified backend config/receipt/source selection
changes. Existing PREPARED records already preserve those pins. The guarded
predecessor request delta remains exactly revision/input manifest/request hash.

## Execution and tests

1. Source tests: original table/seed/schema bytes immutable, exact one-file delta,
   unknown baseline, wrong seed/hash/size, wrong cache/mount, CPU/CUDA dispatch,
   legacy rejection and late-epoch denial. Format/lint/strict types before commit.
2. Existing `publish-private-successor`/audit owner: reuse protected archives,
   preserve old prefix, audit actual successor without model inference. Reuse
   numeric proof/bundle only if the existing closure proves equality.
3. Actual native no-forward admission and fresh sealed receipt; select matching
   verifier/owner/native controls via existing owners. Do not create new Identity
   policy/grant revisions if their actual selection fields did not change.
4. Restore INDEX through its original supported queue/claim/idempotency path.
   Do not re-encode the corpus or replace accepted embeddings to test recovery.
5. Close the old never-started benchmark through its fresh-authorized application;
   run the explicit successor with selected new backends and unchanged six-launch
   sequence. No new Studio login until installation/admission are ready.

The CPU template's mutable `selected-cache` link is part of the stopped release
selection, not an immutable snapshot member. Equal cache bytes do not mean equal
file identity: a new host revision has a different cache inode. After OLD prefix
byte audit and new config publication, but before the native no-forward probe,
the existing root installation owner must compare-and-swap the exact old link to
the new revision under the CPU publication lock. Keep both owners stopped, retain
old target/revision and activation metadata, and independently resolve the same
new pointer after the intentional parent-directory change. Never relax mount inode
checks, add a probe-only template override, or start old controls with the new link.
The later linked-control selection requires this exact new link and its unchanged
epochs; only fresh native probe/seal permits normal owner start. A partial result
is observed explicitly, not blindly retried or automatically rolled back.

### Keep maintenance SDK and numerical runtime identities separate

The older benchmark SDK lacks the current mixed owner configuration contracts.
Use one coherent, current-owner-compatible metadata SDK before its first EOM
import; never mix imported modules from two SDKs or lower an existing schema.
Its package bytes and origins must be verified against pinned installed wheels.
The metadata selector keeps the actual native inventory/admission ledger and
invokes the separately pinned numerical verifier. It does not observe numerical
implementation pins, load an encoder, or import numerical implementation modules.

| Responsibility | Exact source selection | Meaning |
| --- | --- | --- |
| CPU numerical prefix/verifier | `6c4cd95f709ba66756bfcbe2c4528b94cf3622ea` | Byte-audited and actual native admission PASS |
| Installed INDEX service | `e013d35013851a8a5a7b50b8bee9c40edd90568c` | Existing service code preserved |
| Installed QUERY service | `2eef9b20bbd9f1394efc8d1566fada8d37769f66` | Existing service code preserved; actual ExecStart rechecked |
| Maintenance configuration SDK | `2e5b22f35cb9e1bdaf7109aab461bfc0332fb33d` | Current-owner DTOs plus only three reviewed host modules |
| CUDA host publication SDK | `072230c2a0450edfa03af55fa69f5492ba095769` | Explicit-base cache builder fix; no native activation |
| CUDA numerical candidate | `87cc21d68b0b2584c2b683844aea67d759e5bb02` | Built candidate only; qualification remains separate |

E013's inherited ranking helper bytes differ from the frozen native prefix.
That is not numerical equality and does not authorize changing either benchmark
backend. The metadata-only import guard and the separate native verifier enforce
this boundary. No new worker protocol or projection service is needed.

CPU/GPU timing, correctness, physical lease/cleanup and coexistence remain separate
gates. A source or host admission PASS does not activate GPU default. If numerical
identity, driver, resources or authority differs, stop and report that actual delta.

## Source validation — 2026-10-21 UTC

- Host/snapshot/capture/CUDA closure/publication/native-snapshot admission cohort:
  **306 PASS**. New adapter cases preserve the predecessor manifest/revision,
  reject a new baseline paired with its old target seed, and verify explicit CPU
  and CUDA base dispatch. Synthetic fixtures are not native admission evidence.
- Changed Python files pass Ruff/format; the three production modules and new
  adapter test pass strict mypy with imported test fixtures followed silently.
- Broader 29-module cohort initially found one synthetic-fixture regression;
  fixed legacy branch ordering and reran its shared-guard regression successfully.
  Four unrelated schema-registry count assertions remain: expected/actual
  316/345, 322/344, 329/351, 318/333. A clean archive of predecessor
  `757552945a6069df151e77fdbf4ab6f2a6d97cd3` reproduces all four identically.
  No schema bytes, registry entries or those assertions were changed here.
- Reviewed baseline SHA is
  `sha256:e896af20bceb93494f9dd0b724dd0ef01d3ba718c64836b8c4546f4a8a8d7960`.
  With the exact admitted CPU cache, its derived target seed is
  `sha256:9823448841e94d0bc3b599bb572508ad5dd0d4bc1b6683eb295ef73c709a1bc0`.
  These are source-derived candidate identities, not proof of installation or
  host admission. Runtime activation, INDEX recovery and GPU forward remain pending.
