# Protected native embedding runtime admission and actual proof generation

2026-10-12 UTC. DESIGN_ONLY / READONLY_ARCHIVE_DIAGNOSTICS / NOT_IMPLEMENTED /
NOT_ADMITTED / NOT_ACTIVE.
This note proposes the next bounded source vertical after the approved
[native launcher proposal](INCREMENTAL_EMBEDDING_NATIVE_LAUNCHER_PROPOSAL.md).
It does not execute an installer, interpreter probe, root command, DB/DDL, model,
GPU, service, ACL, network, NAS or Git operation. Existing protected prefixes,
archives and historical experiment evidence are not changed or relabeled.
The revision below records authorized non-root archive/metadata/tool observations,
not whole-prefix admission or a retrospective first-instruction certificate.

## Eleven-point boundary

1. **Responsibility/system boundary.** One fixed-profile owner admission leaf audits
   the complete CPU/CUDA successor installation, then derives the existing installed
   numerical proof from actual bytes and independent OS observations. Installation,
   numerical identity, sandbox admission, fresh source authority and default activation
   remain distinct gates. No package solver, downloader, installer framework, runtime
   registry, worker-selected path or arbitrary command execution is added.
2. **Canonical source.** Reuse the retained raw public/private archives under
   `/opt/eom/embedding-runtime-archives/<raw-sha>/<basename>` and exact accepted Git
   source tar. The installed prefix is their explicit executable materialization, not
   another canonical model. The existing canonical model directory, manifest, bytes,
   logical/revision identity and historical CPU environment remain untouched. Read-only
   model ACL installation belongs to the later approved launcher gate, not this leaf.
3. **Identity/revision.** Keep source commit, source-tar raw SHA, wheel raw SHA,
   final prefix-tree SHA, host/tool closure SHA and local admission-receipt SHA separate
   from proof ID/revision/raw/semantic SHA, bundle identity and numeric runtime SHA.
   Complete installation provenance does not replace the small numeric fingerprint or
   cause an unrelated EOM commit to change numerical identity. No mutable latest pointer.
4. **Pointers/checks.** Admit only the two exact fixed prefixes/interpreters below,
   five reviewed lock files, exact public55/70 and private1/2 distribution closure,
   accepted Conda31 candidates, pinned helper/owner inputs and fixed host-tool capture.
   Require root ownership, nonwritable ancestry, safe modes, nlink1 for regular payloads,
   held no-follow FDs, named/FD/ancestor epochs, raw hashes, exact archive/member ownership
   and closed installed additions. Old RECORD or owner-supplied JSON alone is no proof.
5. **Access patterns.** A normalized distribution-name map selects exact archive pins;
   a prefix-relative member map detects duplicate ownership and unexpected files; sets
   close namespaces and ELF dependencies; sorted immutable records produce receipts.
   No repeated directory scan per package, N+1 member lookup or reparsing per inference.
6. **Structures/indexes.** Extend existing public file/distribution boundaries rather
   than copy private parsers. The new leaf owns fixed Conda/host admission orchestration;
   the existing distribution adapter remains the authoritative wheel/member/RECORD rule.
   A local root-private receipt is installation evidence, not an Artifact, DB row,
   authority DTO or new cross-service protocol. No DB/index/schema change is proposed.
7. **Scale/complexity.** O(total accepted archive/installed bytes + members + ELF
   dependency edges), plus O(members log members) for canonical sorted ledger output;
   bounded streaming memory; no second complete prefix/model copy.
   Keep existing wheel limits:20,000 entries,16MiB central directory,2GiB member,
   4GiB expanded wheel; impose an aggregate reviewed profile budget before work.
   Initial proposed Conda limits:31 archives,100,000 combined members,8GiB expanded
   bytes,16MiB metadata and2GiB streamed payload/member; larger legitimate input requires
   review, not truncation.
   The final combined prefix inventory is bounded100,000 members/16GiB; receipts contain
   only small hashes/counts/pins, not a full inventory or package bytes.
8. **Concurrency/transaction.** No DB transaction. Hold the existing fixed profile
   publication reservation throughout audit/proof publication; do not silently create a
   new reservation or run concurrently with snapshot replacement. Recheck prefix and
   host epochs before the first successor instruction and final publication. Materialize
   each small receipt/proof once using root-private O_EXCL reservations, fsync and exact
   read-back; keep interrupted reservations as evidence. No overwrite/repair on retry.
9. **Ownership/dependencies.** Root admits raw-pinned protected helper inputs and
   fixed host tooling; worker UIDs cannot generate/replace proof, edit prefixes, run pip,
   select executables or read owner-only phase evidence. The initial audit runs with the
   independently admitted historical protected interpreter, read-only, `-I -S -B`.
   The successor runs only after whole-prefix admission. The leaf is stdlib-only; a
   fixed independently admitted OS zstd executable is needed for actual `.conda` zstd
   streams because CPython3.12 stdlib cannot decode them. No Python dependency is added.
10. **Failure/retry/idempotency.** Missing/mismatched archive, editable hook, bytecode,
    unregistered/unchecked bytecode, unexpected owner, unsupported relocation/layout,
    duplicate ownership, unsafe ELF/
    loader, stale device capture or uncertain publication denies with content-free codes.
    Existing exact complete evidence may replay only after current installation/host
    revalidation. A changed payload at the same immutable key conflicts. Preserve phase
    evidence; do not chmod/delete files to pass, downgrade pins, download a replacement,
    rewrite direct-URL/RECORD, update old revisions or grant broader access.
11. **Simpler alternative/tests.** A full tree hash plus pip-check/version output proves
    neither independent archive provenance nor the loader actually selected. Conversely,
    numerical proof5/20 intentionally omits transport/base/OS packages. Extend their real
    boundaries with one closed leaf, not a parallel package manager. Synthetic tests must
    prove pre-execution rejection, exact closure, hostile metadata/archives, races and
    replay; actual protected-prefix/device/sandbox probes stay explicit opt-in owner gates.

## Existing supported seams and their actual limits

| Existing source/public symbol | Reuse and limit |
|---|---|
| `scripts/embedding/install_index_runtime.sh`; snapshot `index_runtime_main`, `index_runtime_locks`, `retain_index_archive`, `validate_runtime_tree`, `verify_platform_wheel` | Existing root snapshot/archive reservation and exact lock/profile inventory. Ends `INSTALLED_NOT_ADMITTED / NOT_PROBED / OWNER_GATE_REQUIRED`; no whole Conda/ELF or actual numerical proof. Load only the admitted root-private snapshot helper, never its writable worktree source. |
| Catalog `embedding_runtime_files.NumericalRuntimeFileSnapshots` | Protected FD/hash/epoch/namespace checks. `read` currently requires an already-known expected SHA; `observe_protected_interpreter` verifies identity, not executable bytes. Add one bounded initial-observation primitive in this owner, not a private `_protected_open` import. |
| Catalog `embedding_runtime_distribution.verify_installed_numeric_distribution`, `validate_numeric_console_wrapper` | Exact retained-wheel/member/WHEEL/METADATA/installed-RECORD/addition closure, bounded ZIP inspection before `ZipFile`, compressed-tag support and numeric namespace closure. Reuse this rule through a reviewed stdlib public mechanical seam for complete wheel audit; never use an arbitrary dependency-name plugin. |
| Catalog `embedding_installed_runtime_observer.ProtectedInstalledEmbeddingRuntimeObserver`, `ConfiguredInstalledRuntimeProof` | Actual selected interpreter, numeric archive/member/RECORD and live CPU/proc GPU read-back without ML. Requires an already admitted proof; not the whole-prefix admission owner. Fixed profile/root paths are currently private constants: expose narrow public fixed-profile constants/accessors rather than import them privately or invent different roots. |
| Catalog `embedding_runtime_os_identity.require_native_runtime_interpreter`, `observe_runtime_device`; files `read_live_runtime_os_file` | Exact CPython3.12.13/Linux/x86_64 and bounded live proc checks. CPU parser can expose a capture operation using the same rule. CUDA capability is already captured externally, not observed by its proc reader. |
| Catalog proof contracts `embedding_numeric_library_versions`, `installed_runtime_proof_bytes`, `parse_installed_runtime_proof`, `validate_installed_runtime_proof_pointer`; backend `observed_embedding_implementation_pins` | Existing exact5/20 numeric versions, canonical128KiB proof, separate raw/semantic pointer closure and actual encoder/L2/f32 whole-file pins. Contract parsing establishes no installation or source authority. |
| Legacy CPU verifier `verify_installed_runtime`, `denied_file`, `denied_socket`, `verify_no_network`; Orchestrator `validate_effective_policies` | Reuse the negative-probe/effective-policy approach later. Historical identity/prefix/unit constants prevent applying its PASS to successors; no private cross-service helper imports or modification of legacy branches. |

Exact prefixes are `/opt/eom/conda/envs/eom-embedding-index-cpu` for
`CPU_INDEX_FP32` and `/opt/eom/conda/envs/eom-embedding-cuda` for
`CUDA_INDEX_FP32`; both require their own `bin/python3.12`. The historical
`/opt/eom/conda/envs/eom-embedding-experiment` is neither cloned nor upgraded.

## Required gate before the existing new-interpreter instruction

The current `install_index_runtime.sh` first executes the **new** interpreter for
`index-runtime` after its snapshot publication (currently the final `timeout ...
"$PREFIX/bin/python3.12" -I -S -B ...` call). Its independently accepted tree/helper
hashes are not the complete Conda/ELF/loader audit proposed here. A later proof generator
cannot turn that past instruction into a pre-execution gate. Preserve its actual history.

The reviewed successor changes only this new-profile publisher, not
`install_experiment_runtime.sh` or legacy helper behavior. Exact required sequence:

1. Reject missing/wrong mandatory admission-helper raw SHA and protected owner-input
   raw SHA, plus the existing exact runtime/helper/platform/source/lease/lock pins,
   **before** prefix/identity/package mutation. They are additional closed root-owner
   inputs, not optional flags whose absence retains the old unchecked instruction.
   CPU still rejects lease fields; CUDA requires the exact canonical standalone lease.
2. Acquire/retain the existing exact root profile publication reservation. Copy the
   fixed leaf and its minimal stdlib mechanical source closure into the existing0700
   owner quarantine, pin every leaf against accepted source/wheel bytes and supplied
   raw SHA, and retain FD/named/ancestor epochs. Never execute worktree code or import
   newly installed prefix packages during this audit. Root input pins bind Conda31,
   public/private archives, exact host/tool closure and final logical prefix/tree intent.
3. Use the independently protected historical `bin/python3.12 -I -S -B` to retain/
   recheck exact Conda31/public/private canonical archives and source under the existing
   archive materialization boundary. Inspect all required inputs before replacing a
   prefix; no root Conda/pip/hook/solver/model execution. Invalid input stops here.
4. Keep the existing root snapshot copy/tree/mode/link checks and retained backup;
   publish only the selected new snapshot at its exact final path. Still no successor
   instruction. Run whole-prefix/Conda/ELF/host audit with the **old protected** interpreter
   against this root-owned published snapshot. This avoids resolving final-prefix ELF
   references through the still-developer prefix while auditing a differently named copy.
5. On whole-prefix failure preserve `STAGED_NOT_ADMITTED` and bounded receipt/backup;
   do not invoke the new interpreter, restore/delete data or repair modes. On success,
   recheck held prefix/host/archive/helper epochs and receipt/tree raw pins under the
   same publication reservation immediately before the original fixed final instruction.
   Only then invoke the exact successor `-I -S -B` for its existing helper. That phase
   may independently repeat installation checks but cannot bypass the preceding gate.
6. Numerical proof generation remains later `-I -B` under the same admitted successor,
   using existing public models/observer; it is not optional proof replacing step4.
   Current already-installed prefixes can be audited read-only before their **next**
   invocation; no claim that their original installation used this new source gate.

The worker/native launcher never chooses these owner arguments. Source tests must use
a synthetic successor executable marker and prove that every missing pin, unsafe base,
wrong host closure, failed audit or epoch drift leaves that marker absent. A mocked
successful audit alone is not an installed-prefix PASS.

The small protected owner-input document is local installation input, not a new agent
message/schema or service grant. Its closed required pins are: exact profile/final tree;
snapshot and admission helper raw SHA; fixed mechanical-module closure raw SHA; all five
lock raw SHA; selected public/private archive name/raw SHA and full source-tar/commit pins;
the exact31 Conda source-list raw SHA/member pins and fixed Linux transformation/cache
recipe IDs; fixed zstd/readelf target/alias/host-loader-member raw pins. Existing publisher
arguments must equal those captured pins. No optional wildcard/latest/archive resolver,
command/module/recipe callback, source-authority/operator field or per-request policy is
allowed. Bounds and exact member-name sets are trusted owner release inputs, not numbers
chosen by an untrusted prefix to admit itself. Host updates need new owner acceptance.

## Pre-execution closure: what is independently admitted

The owner supplies an exact reviewed source/lock/archive/prefix/host-tool plan through
protected local inputs, not worker DTOs. Reading bytes is not executing them. The initial
stdlib audit must finish before executing the new prefix, package imports or site hooks.

- **Complete tree and import reachability:** one FD/epoch-bound sorted inventory; no
  writable/group-owned payload, external symlink, socket/FIFO/device, hardlinked regular
  payload, ambient path, editable/egg link, unexpected import archive or namespace member.
  Permit only exact archived internal symlink targets (for example a reviewed interpreter
  alias), not arbitrary in-prefix links. Admit only the exact source-aware canonical
  Conda bytecode ledger below; `-B` prevents writes but does not prevent reads. All
  private EOM bytecode remains forbidden, even if a RECORD registers it. Numeric-wheel
  namespaces keep their existing bytecode denial. This leaf never deletes or rebuilds
  legitimate Conda/stdlib caches merely to satisfy an invented blanket rule. Reject all
  `sitecustomize`/`usercustomize` variants and unreviewed `.pth`; the sole existing exact
  setuptools `distutils-precedence.pth` recipe is a declared exception, whose imported
  `_distutils_hack` bytes must also have accepted archive provenance.
- **Whole wheel closure:** CPU55/CUDA70 selected public archives, platform0.1.0 and
  CUDA-only canonical standalone lease0.1.0; no development/editable distributions.
  Exact wheel raw pins, tags/metadata, archive self-RECORD and member bytes precede
  installed RECORD/addition verification. Only accepted INSTALLER/REQUESTED/direct-URL/
  fixed console-wrapper additions are allowed; direct URLs name the retained canonical
  archive, not worktree/tmp/quarantine. Do not execute any CLI to test its metadata.
  Keep the documented unused upstream `torchfrtrace` target limitation; no forged fix.
  Actual pip26.1.2 wrappers require the additional exact `removesuffix('.exe')` recipe
  demonstrated below; extend the one public wrapper validator with negative fixtures,
  never alter installed wrappers/RECORD to fit older verifier assumptions.
- **Private source closure:** exact full40-character commit and raw Git source-tar SHA
  precede source inspection. The tar's commit comment and every packaged EOM module/
  resource must match the accepted wheel and final installed bytes under the reviewed
  static package/resource mapping, not only the snapshot helper's current eight selected
  platform leaves. Generated dist-info/wrappers use separately checked fixed recipes.
  A historical wheel with the same0.1.0 version is not the new admitted release; adding
  factory/config/benchmark source later requires its real new wheel/source acceptance.
  Canonical standalone lease source/wheel is admitted separately and is never bundled
  into platform ownership. No runtime Git/worktree import is needed for this check.
- **Conda31 base:** raw-pin the exact accepted candidates in the existing installation
  proposal, including Python3.12.13 `hc5f7cf0_3`; retain/reference accepted raw archives
  once. Bounded `.conda` ZIPv2 has only exact metadata plus one info/pkg tar-zstd pair;
  the raw-pinned `_libgcc_mutex` empty metadata/payload exception is explicit below,
  stream decompression through the admitted fixed zstd tool into a bounded tar reader,
  never extract to an executable path or execute post-link/pre-link hooks. Compare
  archive `info/index.json`, `info/paths.json`/noarch metadata with installed exact
  `conda-meta` identities and actual bytes. Reject unmodeled layout/type/link/transform.
- **Installed transformation/ownership ledger:** source archive hashes are pre-link
  bytes. Final Conda noarch mapping, text/binary prefix relocation and generated metadata
  must use the fixed Linux recipe and real candidate fixtures below, not arbitrary
  rewriting or installed `paths_data` self-attestation. List exact
  pip/wheel/setuptools/packaging overlaps: final wheel owns its overwritten members;
  abandoned Conda-only files fail rather than disappear from the audit. The known
  identical `nvidia/__init__.py` references are the one reviewed shared wheel-member
  exception; differing bytes fail. Platform/standalone-lease ownership never overlaps.
  No package hooks run during audit. Unsupported actual relocation is a bounded admission
  gap requiring a reviewed recipe or fresh assembly, not a generic Conda installer.
- **Host ELF/loader closure:** inspect every prefix ELF, actual interpreter and every
  recursively resolved host/tool ELF dependency with an independently admitted fixed
  `/usr/bin/readelf` capture, not `ldd` or an arbitrary ELF execution. Require ELF64
  little-endian x86_64, bounded headers/dynamic/version output, exact interpreter loader,
  DT_NEEDED/SONAME and required symbol versions against the pinned host set. Resolve
  reviewed `$ORIGIN` routes inside the exact prefix; deny relative/developer/writable/
  unknown RPATH/RUNPATH and unexplained SONAME collisions. Record exact root-protected
  loader, GLIBC and selected host-library raw bytes, canonical symlink chains,
  `/etc/ld.so.cache` and its fixed configuration inputs; require `/etc/ld.so.preload`
  absent. CUDA's host driver libraries are explicitly pinned separately from wheel CUDA
  toolkit12.8. No version-string or manylinux tag substitutes for this actual closure.

The diagnostics below narrow the real Conda ledger and two tool candidates. Complete
host/loader routes and root-protected admission inputs remain pending independent owner
acceptance. No diagnostic hash or expected JSON alone makes the installation gate pass.

## Actual read-only Conda/tool ledger,2026-10-12 UTC

The explicit API CPython3.12 interpreter with `-I -S -B` read the accepted candidate
archives under `/tmp/eom-embedding-conda-base-prefetch.KoqIDSXB`; it did **not** execute
either new prefix, import ML, extract packages, invoke Conda or modify files. Fixed
non-root `/usr/bin/zstd -q -d -c` streamed info/pkg tar inspection with bounded reads,
stderr null, owned-child deadlines/reaping. These diagnostics checked all31 raw archive
SHA values and before/after held-FD/named-leaf epochs against `sources.lock`, whose raw
SHA is `3decd31fdcd240cefca05b8fbd708e0dce724f63a3d255684617a6e2fcef010c`.
That outside-Git fixed name/version/build/URL/hash list, not a variable solver result,
supplies the exact31 proposed base rows after independent root acceptance.

| Actual candidate/installed observation | Exact result and admission meaning |
|---|---|
|31 raw archives |56,222,902 bytes; streamed pkg payload7,168 regular members +1,380 links. Reading accepted source bytes does not prove installed ownership/host closure. |
| Archive bytecode1133 | Python779, packaging20, setuptools319, wheel15. Every cache has magic `cb0d0d0a` (CPython3.12), timestamp flags0, matching archive source timestamp/size and `info/paths.json` SHA/size. No bytecode was unmarshaled or executed. |
| Current CPU/CUDA bytecode | Each contains exactly779 caches, all byte-for-byte identical to the accepted Python archive.775 associated source bytes and timestamp/size headers are unchanged/current. No remaining installed generated pip cache or private EOM cache was observed. |
| Four relocated Python sources | Three `_sysconfigdata*` sources and `config-3.12-x86_64-linux-gnu/python-config.py` have reviewed text-prefix relocation and changed size/mtime; their canonical archived caches are stale and CPython ignores them. They remain exact archive bytes, not executable overrides of the relocated source. |
| Overlaid Conda metadata | Each prefix still has31 records/8,924 path rows/1,528 pyc rows.354 archived packaging/setuptools/wheel caches and395 Conda-generated pip noarch caches are absent after wheel overlay. Stale metadata ownership is not authority to recreate/read those absent files. |
| Prefix transformation diagnostic |272 declared relocations:161 binary and111 text. Replay of the fixed Linux encoding/NUL-tail recipe matches161/161 binary +110/111 text in **both** current prefixes. Only `bin/wheel` differs because final accepted wheel/pip-generated wrapper owns it. |
| Narrow archive-format exception | Raw-pinned `_libgcc_mutex-0.1-main.conda` has empty `metadata.json`, zero pkg files and an empty info path list. Other inspected metadata files declare format2. Admit only this exact known archive exception, not arbitrary malformed/missing metadata. |
| Fixed tool candidates | zstd1.5.5 root:root0755/nlink1,1,022,760 bytes, raw SHA `7c5468b370f7c47eda07281e3437fafc568f95d10420051e3aa522709f9342c5`; readelf2.42 is root-owned `/usr/bin/readelf` → `x86_64-linux-gnu-readelf`, regular target root:root0755/nlink1,789,280 bytes, raw SHA `871be389739ecf9924b052c2fde4d2a2068a54e882201b9c34897337a5a0a130`. No file capabilities were reported. Their complete host dependencies still require acceptance. |
| Static interpreter/tool ELF capture | The two new interpreter files were **read**, not executed: loader `/lib64/ld-linux-x86-64.so.2`, RPATH `$ORIGIN/../lib`, libc/pthread/dl/util/m dependencies. zstd/readelf require their observed libc/compression/binutils host libraries. This is not complete installed ELF/loader admission. |

The concrete bytecode rule is a small exact ledger, not a generic cache framework:
only raw-matched canonical Python archive members with the exact CPython magic, cache
basename/optimization and associated source member may exist now. Validate header flags
and actual source identity. A timestamp cache currently accepted by CPython must bind
the admitted source bytes/size/mtime; a stale canonical cache is allowed only when the
exact admitted transformation makes its timestamp/size header invalid and CPython will
compile the admitted source in memory under `-B`. No standalone/sourceless bytecode,
unknown cache, mutated flags/body/header, newly generated cache or private EOM bytecode
is admitted. Source epoch/header changes revalidate before reuse, not just at install.

If a future real assembly requires generated caches, that is a separately reviewed
explicit source→bytecode recipe: protected CPython3.12.13 `compile` of already verified
source with exact co_filename/optimization/header recipe, local `marshal.dumps` and
byte comparison, without `marshal.loads`, eval or execution of submitted code. No such
exception is needed or activated by the current779 observed caches.

The real Linux prefix recipe is limited to the272 declared paths and two fixed prefixes:
perform the declared text replacement in the five existing Conda encodings; binary
replacement changes only placeholder-containing NUL-terminated spans, retaining length
with tail padding (not blind placeholder padding inside a path). These fixed prefixes
contain no spaces and the admitted text shebangs do not need environment activation or
long-shebang fallback. Validate original archive bytes, declared placeholder/mode and
computed final bytes. The diagnostic replay read installed/cache metadata and inspected
Conda `core/portability.py` source, but never imported/executed developer Conda; full
admission must obtain the authoritative original members directly from retained archives,
not trust an extracted package cache or `sha256_in_prefix`. No general relocation engine,
Windows/macOS branch, hook or mutable correction table is proposed.

### Narrow actual console-wrapper source compatibility

Installed CPU torchrun/f2py/transformers-cli and CUDA proton demonstrate the pip26.1.2
distlib recipe `sys.argv[0] = sys.argv[0].removesuffix('.exe')`. The existing numeric
validator accepts two older exact byte recipes, so real proof generation would currently
reject these legitimate closed wrappers. The root-approved local source correction adds
only this third exact recipe with the same fixed interpreter shebang and archive-derived
module/callable. Preserve both older recipes, error/API and archive-entry metadata checks;
no AST whitelist, installed-byte rewrite or wrapper execution. Focused tests cover all
three CPU/CUDA recipes, malicious statement/argument/function/module/shebang/newline
variants, and full retained archive/installed RECORD metadata association. This local
compatibility change is not a whole-prefix/proof/model/GPU admission PASS.

Local compatibility source gate:179 proof/observer/distribution tests PASS, including62
new three-recipe/mutation/metadata-association cases;436 model-free ten-suite embedding
regression tests PASS. Ruff lint/format on the three owned Python files and core strict
mypy with `--follow-imports=silent --explicit-package-bases` PASS. These tests use small
synthetic wheels/prefixes and never execute a wrapper or installed ML/runtime/model/GPU.
The broader admission leaf/pre-execution gate/Conda-loader receipt remains design-only.

## First mechanical source phase

Root accepted this proposal and approved a four-path source-only extraction after the
wrapper correction commit. The existing wheel/RECORD/member/wrapper rule now lives in
public `embedding_runtime_wheel_closure.py`; the numeric adapter delegates and retains
its typed API/error/results. Five small frozen local pin/result values do not define a
new protocol or authority DTO; direct core inputs are type/hash/name/bounds checked again.
The core imports only stdlib and the real existing protected-file adapter, permitting
the planned old-interpreter `-I -S -B` owner audit without unadmitted third-party imports.
Source gate:241 focused tests PASS (185 current numeric/proof/observer +56 new direct
core cases),515 eleven-suite model-free embedding regression tests PASS, scoped Ruff
lint/format3 and strict mypy3 PASS. The actual explicit API `-I -S -B` subprocess imported
the real updated protected-file adapter and core, not stubs, with no Pydantic/schema/
Identifiers/ML modules imported. Original distribution test/fixture bytes were unchanged.
An initial in-progress doubled-backslash filename-regex mistake caused fixture rejection;
it was corrected to the exact existing contract pattern, not a flavor/bounds relaxation.
No proof/config/installer/host/Conda or protected-prefix behavior is implemented by this
phase; the mandatory pre-successor gate and all real admission/benchmark actions remain pending.

## Fixed OS captures and deriving the real numerical proof

The admitted helper accepts only closed modes/profile/pinned owner input identities, not
arbitrary executable/command/URL/path selectors. Owner-side external captures use exact
argv, scrubbed environment, bounded selector/stream reads while the child runs, stderr
DEVNULL and timeout; reject output overflow before allocation, not after `capture_output`.
Kill/reap only the owned child/process group on failure. Initial per-tool bounds:10s,
1MiB for ELF output per file and16KiB for GPU capture, with an aggregate90s host-capture
deadline; legitimate larger output requires reviewed bounds, not truncation.

CPU hardware comes from the existing `/proc/cpuinfo` homogeneous vendor/family/model/
stepping rule. CUDA additionally requires the actual admitted shared physical lease,
all-entrypoint/drain/device policy and unknown-PID/device-idle gate before capture.
An independently pinned `/usr/bin/nvidia-smi` uses a fixed GPU0 UUID/PCI/name/driver/
compute-capability query; actual supported field/format/exit behavior must be admitted
with the installed580-series tool before freezing that argv. Unknown/unsupported output
denies; no fallback to marketing name or advertised CUDA compatibility. Cross-check
the resulting exact UUID/PCI/model/driver with the existing proc GPU files, actual minor0,
boot ID and character-device major/minor identity. Proc paths derive only from validated
captured PCI identity. The later actual backend rechecks Torch build and capability.

After whole-prefix admission, the same raw-pinned leaf runs under the exact successor
`bin/python3.12 -I -B` with no developer PYTHONPATH/home/loader/shell injection. Its fixed
site hooks are now admitted. Before ML/model imports:

1. Observe raw SHA/size of the actual installed numeric RECORD, direct-URL and derived
   console wrappers via the new bounded protected-file observation seam; obtain actual
   REQUESTED presence and exact accepted raw archive identity/size. Expected archive
   hashes come from the owner-admitted locks, not installed metadata.
2. Construct the existing proof5/20 with fresh actual CPU/CUDA capture, exact Python and
   statically parsed installed Torch version/build. Validate every distribution using the
   same public wheel/installed-member verifier, then close covered namespaces/epochs.
3. Serialize through existing canonical proof functions; validate both raw and semantic
   hashes and exact IDs/revision/profile. Publish once at the existing
   `/opt/eom/embedding-runtime-proofs/<proof-id>/<revision>/proof.json`, initially under
   a root0700 reservation and only expose a complete root-owned read-only revision after
   held-FD/read-back/parent fsync acceptance. An existing incomplete revision is not repaired.
4. Read back with `ProtectedInstalledEmbeddingRuntimeObserver` under the actual exact
   successor; CPU has no GPU handle, CUDA must supply an owner-captured live ownership
   handle and revalidate it. No forged success from a function that merely echoes proof.
5. Observe installed implementation pins through `observed_embedding_implementation_pins`;
   derive descriptor with the fixed batch4/thread4/interop1 eager FP32/no-TF32 recipe and
   actual archive/device pins. Create only small execution model/bundle successor metadata
   referring to the unchanged legacy payload/upstream/files/pooling/prefix/dimension/L2/
   truncation/token ceiling. Bundle/config generation belongs to the existing reviewed
   schema/owner boundaries, not a new leaf-defined JSON protocol or worker grant.

The new config1.0 proposal pins existing bundle/proof/runtime/resource references, not
an admission-receipt field. Do not widen it here. A small separate local root-protected
receipt records source/locks/prefix/Conda/host closure and proof/bundle/config raw pins;
its expected raw SHA is accepted by the installed owner/unit-verifier release context,
never by self-hashing JSON. Future native factory admission must recheck these current
epochs/host/prefix pins before ML imports. Receipt presence alone does not prove that
the effective unit, installed source, current device or authenticated operator is valid.
Implement the single root-approved factory port
`NativeEmbeddingInstallationAdmission.assert_current(profile, configuration_id,
configuration_revision_id, configuration_raw_sha256)` using its exact keyword pins.
There is no second public whole-prefix receipt port, default boolean grant or transferable
admission DTO. The later concrete adapter privately captures exact protected receipt/
prefix/host epochs and denies absent/stale/mismatched capture; permissions remain separate.

## Minimum proposed next source paths and approval sequence

| Proposed path | Narrow owner change |
|---|---|
| `scripts/embedding/install_index_runtime.sh` | Mandatory new-profile pre-execution gate above, using the old protected interpreter before its existing new-Python instruction. Missing required pins cannot retain an unsafe compatibility fallback. Historical installer/branches remain unchanged. |
| `scripts/embedding/admit_index_runtime.py` (new) | One stdlib fixed-profile two-phase admission/proof leaf; protected snapshot/source/helper intake, exact Conda/host ledger, no model/pip/solver/network or arbitrary command dispatch. Root-quarantine execution only; not writable-worktree imports. |
| Catalog `embedding_runtime_wheel_closure.py` (new); existing `embedding_runtime_distribution.py` | One purpose-named stdlib public mechanical wheel/RECORD/member closure, justified by pre-execution whole-wheel audit and existing typed numeric observer. Plain frozen member observations; existing distribution adapter constructs the same typed numeric proof/pins. Extract/delegate the current rule, do not duplicate it. Protected quarantine loads only this admitted minimal module closure, not unadmitted Pydantic/site packages. Root reviews this seam before refactor. The separately approved third-wrapper-recipe local fix does not implement it. |
| `services/catalog_service/eom_catalog_service/embedding_runtime_files.py` | Initial bounded observed-member SHA/size/bytes plus retained FD/epoch semantics; existing expected-hash paths delegate/reuse and keep behavior. No uncontrolled read API or live OS registry. |
| `services/catalog_service/eom_catalog_service/embedding_runtime_os_identity.py`; observer module | Shared CPU-capture parser and public exact fixed-profile/root accessors; CUDA owner capture stays outside the numeric observer. Preserve existing observation semantics. |
| `tests/unit/test_embedding_runtime_admission.py` (new); existing file/distribution/observer tests | Synthetic complete-prefix/archive/Conda/host/tool/proof fixtures and pre-execution ordering/replay/race tests. No installed model/GPU/network/DB fixture. |
| `tests/integration/test_embedding_runtime_admission.py` (new, later opt-in) | Exact protected disposable-prefix/tool/UID negative probes only after source review and explicit owner preparation; model/physical-device/unit benchmark is a separate authorized gate. |

Root first reviews this proposal and exact mechanical public seam before behavior.
Next freeze schema-independent admission code and synthetic gates, then independently
review the real archive/Conda transformation/host-tool ledger. Root performs read-only
whole-prefix admission on the current new CPU prefix, derives/proves CPU evidence, and
reviews the real fixed factory/unit/config/UID/read-only model ACL probes. Failure keeps
the existing installed/archive state and small receipt/phase evidence; no re-publication
or historical rollback mutation. If a successor must be reassembled, preserve the exact
rejected new prefix under the existing reviewed publication recovery process and use a
new independently accepted snapshot; never edit installed package/RECORD files in place.

Then root admits CUDA prefix independently and completes **all** image/direct GPU
entrypoint drain/shared-lease/device-idle/orphan reconciliation gates before real device
capture or CUDA model execution. Static ELF closure alone cannot prove libraries loaded
via `dlopen`; a separate constrained native-UID no-forward import probe must reconcile
actual `/proc/self/maps` with admitted host/prefix members before model work, without
executing third-party ML code as root. Its effective sandbox and fixed driver/device
access must pass the launcher admission first. Preserve the direct-single-process
abnormal-last-close limitation; flock alone is not orphan cleanup proof.

Finally wire actual owner/source/IAM/Job fences and the approved benchmark21-phase
transport, not the index3FD EOF adapter; execute the mandatory identical-input CPU/CUDA
cold/warm/query/ranking/capacity protocol under its **unchanged predeclared** gates.
Initial RSS≤6GiB and independently measured CUDA reserved/process VRAM≤8GiB remain
distinct. If superior and correctness/isolation/capacity/lease gates pass, perform the
reviewed actual CUDA-default policy/index/query activation with exact read-back and
CPU rollback, rather than stopping at proof installation or benchmark-only status.
Until then: INSTALLED_NOT_ADMITTED / NOT_PROBED / CUDA_NOT_ACTIVE remains explicit.

## Next source phase: exact Conda31 byte-audit plan (review freeze)

2026-10-12 UTC. ROOT_APPROVED_SOURCE_PHASE / SYNTHETIC_GATES_PASS / NOT_ADMITTED. Root committed the
mechanical wheel extraction in `73fe4d95` and the native factory/public file-profile
seams in `9ace25e6`. The following five-path phase is a **read-only Conda31 byte audit**,
not whole-prefix/host ELF admission, proof generation or an implementation of
`NativeEmbeddingInstallationAdmission`. No installer, protected-prefix, old helper,
production privilege, model, GPU, DB, migration or runtime action is included.

| Owned path | Exact addition |
|---|---|
| `scripts/embedding/admit_index_runtime.py` (new) | Closed `conda31-bytes` CLI; protected owner-input/root-context intake and sanitized partial-audit result only. No install/copy/repair or new-interpreter invocation. |
| Catalog `embedding_conda_runtime_closure.py` (new) | Stdlib-only archive→transformation→installed Conda survivor/cache/link/overlap ledger. Calls the existing public wheel core for the four exact overlays; no second wheel validator. |
| Catalog `embedding_runtime_files.py` | Only the coordinated bounded initial-byte observation below; preserve existing expected-byte APIs, error behavior and ancestor/FD/named epochs. No changes to factory/observer ownership. |
| `tests/unit/test_embedding_conda_runtime_admission.py` (new) | Synthetic archive/prefix/tool-ownership fixtures, malicious inputs/races, exact transformations/cache rules and real isolated stdlib import-closure tests. No actual protected installation or model/device/DB test. |
| This admission note | Approved scope, measured source gates and explicit still-unavailable whole-prefix/runtime gates. |

### Public values and invocation shape

The new module exposes one purpose-specific operation:

```text
audit_installed_conda31(plan: CondaRuntimeAuditPlan, *,
    prefix: Path, archive_root: Path, files: NumericalRuntimeFileSnapshots,
    tool_admission: CondaArchiveToolAdmission) -> CondaRuntimeByteAudit
```

`prefix` and `archive_root` are captured trusted owner locations, not fields in the
plan. The CLI supplies only `fixed_native_embedding_profile(profile).prefix` and
`/opt/eom/embedding-runtime-archives`; non-root synthetic tests substitute isolated
temporary locations through this infrastructure boundary. `files.owner_uid=0` is
mandatory in the real CLI. No worker-supplied directories or command/module selectors.

Three small frozen local values are sufficient: `CondaRuntimeArchivePin` contains
`filename`, `sha256`, `size_bytes`; `CondaRuntimeAuditPlan` contains `profile`,
`source_list_sha256`, `source_list_size_bytes`, exactly31 sorted archive pins and
exactly4 sorted existing `RuntimeWheelArchivePin` overlay pins;
`CondaRuntimeByteAudit` contains only the profile, source-list/raw-archive/overlay
closure hashes, transformation/member/cache counts and deterministic ledger SHA.
These are local immutable values, not protocol/authority DTOs, registries or receipts.
Revalidate **all** direct values, nested pin types and tuple bounds at the public
operation, including constructed/copied instances, before allocation, file reads or
child creation. Exact integers exclude booleans; hashes are `sha256:` plus lowercase64;
bounded ASCII filenames cannot include a directory or select another archive type.

The closed CLI arguments are `conda31-bytes --profile CPU_INDEX_FP32|CUDA_INDEX_FP32
--owner-input /opt/eom/.embedding-index-install-XXXXXXXX/conda31-audit-input.json
--owner-input-sha256 sha256:<64>`, where `XXXXXXXX` is exactly the existing eight-character
ASCII alphanumeric quarantine suffix. The path is existing-only/root-protected under
that exact pattern, not an arbitrary input/output path. Its ≤64KiB unique-key JSON has
only `profile`, `source_list_sha256`, `source_list_size_bytes`, `archives` and
`overlay_archives`, matching the value fields above; no own hash, permissions, arbitrary
recipe, tool command, URL, operator, accepted flag or resource-budget field. Owner
expected raw SHA remains a separate trusted invocation pin. The fixed five protected
lock copies are siblings under the same quarantine's `locks/`; the source-list location
is derived as `<archive_root>/<source-list-raw-sha>/sources.lock` and every archive path
as `<archive_root>/<archive-raw-sha>/<filename>`.

Root must execute only the raw-pinned leaf/minimal module snapshot with the independently
protected **old** CPython3.12.13 `-I -S -B`, scrubbed environment and the existing retained
publication reservation. CLI root UID, interpreter/isolation flags, protected source/
input ancestry and expected raw pins are prerequisites, not declarations inside JSON.
Missing canonical source-list/31 archives/four overlays/locks or a real independently
accepted tool context returns unavailable **before spawning**. This source phase does
not create archives/quarantine/receipts, acquire/create a publication reservation or
load an optional provider. Standalone invocation cannot synthesize the missing tool
context: until its real owner composition is admitted, it denies rather than treating
root-owned JSON as a grant. Successful library output means
`CONDA31_BYTES_AUDITED_NOT_ADMITTED`, never READY, whole-prefix or native admission.

### Initial observed-byte seam, with existing lifetime checks

Add the small frozen value `ObservedRuntimeMemberBytes(sha256: str, size_bytes: int,
raw: bytes)` and exactly
`NumericalRuntimeFileSnapshots.observe_protected_member_bytes(path, *, maximum)`.
The method accepts an exact positive integer maximum≤8MiB, including legitimate
zero-byte regular members (actual empty-byte SHA and size0); enforce a16MiB aggregate
retained-observation budget before reading, with `st_size` and held-FD epochs checked
before allocation. Reuse this owner's protected open internally; never expose/private
import `_protected_open`. Return actual SHA/size and the single bounded immutable raw
value, retain its exact file/ancestor/named epochs, and check them after the read.
An existing identity-only observation can upgrade only through this new explicit method
after exact epoch revalidation. A hashed or already consumed observation is not reread.

The existing `verify` may match a new observed SHA/size and check epochs without hashing
again. The first existing expected `read`/`verified_open` for this new observation can
reuse the retained raw bytes under the exact expected SHA/size/maximum and fresh held
FD/named/ancestor checks, then consume the observation's reuse slot. Existing callers
that did not use the new observation keep their current repeated-read denial and
duplicate-reference semantics. A mismatch or too-small bound fails, never silently
reopens/reparses. Retained observations share the original bytes object, not a new copy;
small RECORD/direct-URL/Conda metadata inputs can therefore seed exact existing wheel
pins without repeated byte hashing. No unbounded unknown-hash read or OS-file cache.

### Fixed31 source and exact four-overlay ownership

The authoritative source-list raw SHA is
`sha256:3decd31fdcd240cefca05b8fbd708e0dce724f63a3d255684617a6e2fcef010c`.
Its raw-pinned rows supply exact filename/name/version/build/subdir/URL/archive SHA,
not the installed metadata or a package cache. Require the exact31 distinct names:
`_libgcc_mutex`, `_openmp_mutex`, `bzip2`, `ca-certificates`, `ld_impl_linux-64`,
`libexpat`, `libffi`, `libgcc`, `libgcc-ng`, `libstdcxx`, `libuuid`, `libxcb`,
`libzlib`, `ncurses`, `openssl`, `packaging`, `pip`, `pthread-stubs`, `python`,
`readline`, `setuptools`, `sqlite`, `tk`, `tzdata`, `wheel`, `xorg-libx11`,
`xorg-libxau`, `xorg-libxdmcp`, `xorg-xorgproto`, `xz`, `zlib`.
All URLs are the exact source-list rows, with only pip/tzdata under `noarch`; no network
operation follows them. Plan archive SHA/name must equal these rows and actual bounded
sizes; the31 archive byte hashes are checked before decompression. The known mutex
empty-metadata/zero-payload exception remains exact raw-pin-specific.

The fixed5 lock raw pins above select identical overlay archives for both profiles:

| Overlay | Exact archive filename | Raw SHA (without `sha256:`) |
|---|---|---|
| packaging26.2 | `packaging-26.2-py3-none-any.whl` | `5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e` |
| pip26.1.2 | `pip-26.1.2-py3-none-any.whl` | `382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab` |
| setuptools83.0.0 | `setuptools-83.0.0-py3-none-any.whl` | `29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3` |
| wheel0.47.0 | `wheel-0.47.0-py3-none-any.whl` | `212281cab4dff978f6cedd499cd893e1f620791ca6ff7107cf270781e587eced` |

Pin matching is derived from those exact protected lock bytes, not latest or arbitrary
distribution selection. Initially observe each actual installed RECORD/direct-URL/
console wrapper and REQUESTED presence, construct the existing mechanical pin, then
call `verify_installed_runtime_wheel`. Use its returned installed-member sets as the
only final wheel ownership; allow shared members only with identical bytes. The four
overlaid Conda packages must have exactly their archive-derived obsolete-only members
absent, not merely ignore all Conda `site-packages`. Unexpected survivors, missing
non-overlaid survivors and conflicting ownership fail. No other public/private wheel
or namespace is certified in this phase. Prefix-wide unexpected-member closure remains
the next whole-prefix audit; this partial output does not cover unrelated additions.

### Bounded archive,272-relocation and canonical-cache ledger

Before `ZipFile`, bound the existing `.conda` EOCD/central entry structure to exactly3
members and≤64KiB directory metadata; permit only exact `metadata.json` and matching
`info-<archive-stem>.tar.zst`/`pkg-<archive-stem>.tar.zst`, with no central/general ZIP64
(only the approved local equal-size encoding below), encryption,
unsafe aliases or compression-method surprise. Only canonical raw sources are inputs.
Prototype size bounds precede streams:31 archives≤64MiB combined raw bytes,100,000
combined tar members,8GiB expanded bytes,2GiB streamed payload/member,≤16MiB total
parsed metadata,≤1MiB per installed Conda record, and≤64MiB per transformed member.
These comfortably cover the observed56,222,902 raw bytes/7,168 files/1,380 links and
largest declared relocation31,498,184 bytes. Bounds are fixed owner source constants,
not values supplied by a prefix. Keep only path/pin/type/link/source-association records
in keyed maps; consume large payloads once in chunks and discard them, never retain a
full prefix/archive dictionary of file bytes. One transformed member has an explicit
bounded temporary source/computed-byte comparison boundary, not another canonical copy.

Tar headers/types/size and bounded POSIX-PAX overrides are inspected before payload
read/concatenation; reject sparse/device/hardlink/unmodeled extension records. Regular
file hashes/sizes, directory metadata and symlink targets must match accepted
`info/paths.json`; source `info/index.json` and noarch metadata determine Linux identity
and the closed Python/generic path mapping. Link targets may use reviewed relative
parent components only when the archive-declared chain remains entirely in the exact
prefix, with cycles/escape/type changes denied. The new Conda adapter owns this narrow
archive-declared symlink observation and held ancestor/named-link/target epochs because
the existing public file adapter intentionally accepts regular members only; it does
not reach into that adapter's private opening code. No extraction or package hook.
Compare generated Conda records' fixed source identity/common metadata and exact mapped
path associations with the archive ledger; bound/validate generated local metadata but
never trust `sha256_in_prefix`, stale `link.source` or `files` as executable ownership.

Recompute the source-declared272 relocations (161binary,111text) in the exact two
profiles: five fixed Linux Conda encodings; text placeholder replacement; binary only
placeholder-containing NUL-terminated spans with length-preserving tail padding.
Enforce original source hash/size, declared mode/placeholder, prefix-length and final
byte hash/size. No activation/space/long-shebang fallback, general transform callbacks
or installed correction table. The one `bin/wheel` source-declared transformation is
still recorded, but its final bytes are owned/verified by the accepted overlay wheel.

Derive the1133 archived bytecode/source associations before installed comparisons.
Require exactly the779 Python survivors with canonical raw member SHA/size,
CPython3.12 magic `cb0d0d0a`, timestamp flags0, closed `cpython-312` basename/optimization
and exact `.py` archive source identity/header.775 caches must remain current for the
same admitted installed source SHA/size/mtime. Only the exact four source members named
above may have stale canonical cache headers after their verified text relocation;
require actual timestamp/size mismatch so CPython cannot execute that stale cache.
The354 packaging/setuptools/wheel archive caches and395 generated pip noarch caches
must be absent, with archive/noarch source associations retained as removal evidence.
No bytecode unmarshaling/compilation/execution, inferred cache repair, private EOM cache,
unregistered/sourceless cache or blanket deletion. Metadata-listed absent paths are
not recreated. Failure leaves the existing canonical assembly unchanged.

### Mandatory accepted tool handle and source gates

The one small purpose-specific port is `CondaArchiveToolAdmission.assert_current()
-> None`: a mandatory independently accepted owner-captured zstd executable/host-loader/
dependency/environment lifetime fence, **not** a Boolean or serialized acceptance field.
Its concrete trusted capture/loading belongs to the later fixed OS closure phase; this
phase does not admit a tool from its own observed metadata. Require that exact handle
before any child, before/after every tool use and before returning a partial audit.
There is no optional default, command callback, import-by-name provider or runtime
plugin registry. The module owns the sole fixed invocation `/usr/bin/zstd -q -d -c`,
scrubbed env/known cwd, exact raw executable pin above and protected FD/named epochs.
The independent handle must also cover fixed loader/dependency/cache/alias routing and
no capabilities/preload injection; an executable SHA alone is insufficient. Readelf
is not invoked by this phase and its candidate pin above confers no acceptance.

Feed/read the owned zstd child concurrently with bounded buffers, stderr DEVNULL,
absolute deadline and explicit overflow denial; no `capture_output` then size check,
chunk-reset timeout or shell. Cap each tool stream at10s and each full audit at180s;
terminate/reap only the owned child on any error and retain source/prefix epochs.
The child emits decompressed bytes only and cannot select files, archives or hooks.
Missing/stale tool ownership or any epoch/bounds/hash/layout discrepancy returns a
stable content-free unavailable/invalid result, never partial semantic success.
The partial result is nonpersistent; replay reads the same exact inputs and revalidates
current epochs. No repair/retry within the audit or own O_EXCL publication yet.

Focused tests will cover direct bool/integer/nested mutation rejection before I/O;
missing canonical inputs/tool handle before spawn; small real child timeout/overflow/
contention-free cleanup under a synthetic tool fence; safe/hostile ZIP/tar/PAX/link/
owner/mode/hardlink/epoch cases; all five encodings and binary-span padding; exact
four overlay/removal conflicts; current/stale/mutated/source-less cache association;
metadata self-attestation rejection; old expected-file repeated-read behavior plus
initial-observation reuse/caps/races; canonical partial ledger determinism and both
profiles. Run real `-I -S -B` import closure against the current real files/wheel/Conda
modules, scoped Ruff/format/strict mypy and existing distribution/observer/factory
regressions. Fixtures are synthetic and source gates are not a protected-prefix PASS.

**Subsequent approval boundary:** fixed host/tool ELF/loader acceptance, full55/70+
private/source/whole-tree closure, root archive materialization/receipt/proof generation,
the mandatory old-interpreter-before-new-instruction installer integration, concrete
factory admission, launcher UID/ACL/unit probes and actual CPU/CUDA benchmark/default
activation remain separate required work. This source phase cannot satisfy them.

### Original-archive compatibility evidence and proposed narrow corrections

2026-10-12 UTC. READONLY_DIAGNOSTIC / ROOT_APPROVED_NARROW_SOURCE_RULES / NOT_ADMITTED. Root authorized
non-root fixed zstd reads of the two aliases, their two target-owner archives and the
same fixed31 archives' licensing classification. Every original candidate was opened
regular/nlink1/O_RDONLY/NOFOLLOW/CLOEXEC; held raw SHA/size and FD/named epochs matched
the exact source list before/after. Bounded headers/metadata/payload reads used the
fixed `/usr/bin/zstd -q -d -c`, scrubbed environment/stderr null,10s per child/180s total
and owned cleanup. The31 diagnostic finished in0.655s, reading original archive bytes,
not a package cache or successor interpreter. No write, installation, ML/GPU/DB/root
action or tool/full-prefix admission occurred. These observations are **not** supplied
as a real `CondaArchiveToolAdmission` handle.

The original archives account exactly for7,168 regular tar members:7,147 declared
regular payloads plus21 undeclared **licensing metadata**; all1,380 links are declared.
Every declared regular member's original raw SHA/size matched its `info/paths.json`
row. No missing/duplicate/other undeclared executable member was encountered.
Therefore neither previous count is discarded, and no21-path ignore rule is proposed.

All93 central ZIP entries have empty extras and bounded ordinary32-bit sizes, with
no ZIP64 EOCD/locator.42 local headers instead use the exact local-only size form:
version45, both local size fields `0xffffffff`, extra tag0x0001/length16 containing
uncompressed/compressed uint64 sizes equal to the bounded central values. For example:

| Exact original archive/member | Held source result |
|---|---|
| `python-3.12.13-hc5f7cf0_3.conda`, raw SHA `23572134eb5b0c89673831ceb575c883425039c01778fcaed5ebf5cc513e2a84`,31,709,996 bytes; `pkg-python-3.12.13-hc5f7cf0_3.tar.zst` at offset74 | central size31,571,924; local extra `01001000d4bfe10100000000d4bfe10100000000` |
| `zlib-1.3.2-h47b2149_0.conda`, raw SHA `4bb61142e8fe22510086c1030e1ff3ad4888ebf9bf0a11e9931594e8549a9d42`,94,060 bytes; `pkg-zlib-1.3.2-h47b2149_0.tar.zst` at offset74 | central size86,801; local extra `01001000115301000000000011530100000000` |

**Proposed ZIP diff:** validate each local header/name/flags/method/CRC and body range
before opening its member. Accept ordinary local sizes with no extra, or **only** the
exact form above with equal bounded central sizes. Reject central extras, true ZIP64
EOCD/locator, other local extensions/sentinels, descriptors/encryption, inconsistent
sizes/names/overlapping body ranges. The earlier blanket wording is corrected to "no general
ZIP64; only this fixed local-size encoding". No library-wide ZIP parser
relaxation or changes to the existing mechanical wheel validator.

The exact cross-package aliases are original tar type2/size0/mode0777; their referring
softlink SHA describes a build-time target, not the symlink text or current owner:

| Original referring alias | Original independently pinned target owner |
|---|---|
| Python raw pin above: `compiler_compat/ld` → `../bin/x86_64-conda-linux-gnu-ld`; info SHA `70d094c82cbcf7b2f2447c475c57e965b54f8e7698f82ca1871a4a015b2d5634`, size2,941,304 | `ld_impl_linux-64-2.44-h9e0c5a2_3.conda`, raw SHA `4a4875ab4354d4a1bf1695850efad8787d7063387ed6b5aec5ecb659869e2590`,742,162 bytes; original `bin/x86_64-conda-linux-gnu-ld` SHA `e5e2063623d80bd5956391561faf35295bacaa03af1c0c1f6e4391d08d48364f`, size2,941,304. Original info/payload match; target has its own declared binary relocation. |
| Zlib raw pin above: `lib/libz.so` → `libz.so.1.3.2`; info SHA `d1e842e199a902992c7b778b8482f4777ccd3cbe9c26f8a44c783d9e6601da79`, size117,416 | `libzlib-1.3.2-h47b2149_0.conda`, raw SHA `02b0d3bad12d15c668f06a32283907608bcfb49ca40d9d09d3bcfe6bd4765f31`,61,662 bytes; original `lib/libz.so.1.3.2` SHA `0900010993ecb9e3bf674459147f3433b5b001aeea94d5ba43b61c867e596cd1`, size117,416. Original info/payload match. |

**Proposed link diff:** bind the referring original raw archive + exact alias/type/text/
info row. Permit only those two closed cross-package owner associations; independently
validate the resolved target's **own** original/relocated final pin and retained epochs.
Same-package aliases bind the target owner's original pin; the two source-declared
directory aliases (`ncurses:lib/terminfo`→`share/terminfo`, `python:lib/python3.1`→
`lib/python3.12`) require their original softlink type/exact spelling, internal directory
ownership, SHA `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
(digest of empty bytes, **not a blank SHA string**) and size0. Blank source SHA is rejected.
No use of stale referring SHA as target authority,
unresolved link, hash repair, arbitrary cross-package route or generic exception.

All21 auxiliary regular members are under `info/licenses/`, zero executable materialization
authority, and fixed by the original archive's raw pin. The exact proposed closed ledger
is below; full original archive pins remain the fixed source-list rows, not this table:

| Package / member suffix under `info/licenses/` | Size | Original member SHA |
|---|---:|---|
| `_openmp_mutex` / `LICENSE` |1510|`d939c95d76d470fe1796d8a24ca1ee28c920fc85f61c57059de993586fa60071`|
| `bzip2` / `LICENSE` |1896|`c6dbbf828498be844a89eaa3b84adbab3199e342eb5cb2ed2f0d4ba7ec0f38a3`|
| `ld_impl_linux-64` / `COPYING3.LIB` |7639|`a853c2ffec17057872340eee242ae4d96cbf2b520ae27d903e1b2fef1a5f9d1c`|
| `ld_impl_linux-64` / `COPYING` |18002|`231f7edcc7352d7734a96eef0b8030f77982678c516876fcb81e25b32d68564c`|
| `ld_impl_linux-64` / `COPYING3` |35147|`8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`|
| `ld_impl_linux-64` / `COPYING.LIB` |25291|`56bdea73b6145ef6ac5259b3da390b981d840c24cb03b8e1cbc678de7ecfa18d`|
| `libffi` / `LICENSE` |1132|`67894089811f93fca47a76f85e017da6f8582d4ba0905963c6e0f1ad6df7a195`|
| `libuuid` / `Documentation/licenses/COPYING.BSD-3` |1391|`9b718a9460fed5952466421235bc79eb49d4e9eacc920d7a9dd6285ab8fd6c6d`|
| `libxcb` / `COPYING` |1337|`c5ffbfeaa501071ceeb97b7de2c0d703fdaa35de01c0fb6cbac1c28453a3e9fd`|
| `libzlib` / `LICENSE` |1002|`e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2`|
| `ncurses` / `COPYING` |1447|`b2feb54f39529abe226f709a292584fde48a2e5721559fee417d2cdd51cb7cc1`|
| `openssl` / `LICENSE.txt` |10175|`7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a`|
| `readline` / `COPYING` |35147|`8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`|
| `sqlite` / `LICENSE.md` |263|`9c6479123f32a1ed50d9a0af203dfe8972e65035b0cdeef436b5f8d0924517fe`|
| `tk` / `tcl8.6.15/license.terms` |2255|`c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16`|
| `wheel` / `LICENSE.txt` |1107|`30c23618679108f3e8ea1d2a658c7ca417bdfc891c98ef1a89fa4ff0c9828654`|
| `xorg-libx11` / `COPYING` |46458|`2e7012a140f000735a7172674a2d314398d79622444fba65d108b029b29ab283`|
| `xorg-libxau` / `COPYING` |1148|`56abe29bb1d9806a9e04fa9f80fed2c0f18027594df3f098148d814aef6bddfa`|
| `xorg-libxdmcp` / `COPYING` |1178|`8a3c3f35b0dbcb60a4e242b9e4394a352a65bb27deb2938ea1e2e62a626e16e9`|
| `xz` / `COPYING` |3119|`616a3ad264ce29b8f1cb97e53037b139d406899ca8d1f799651e17bfa09830b8`|
| `zlib` / `LICENSE` |1002|`e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2`|

**Proposed licensing diff:** consume/hash each bounded≤1MiB original auxiliary member,
require the exact package/path/size/SHA above and count21, and incorporate sorted metadata
pins into the partial ledger digest/count. These paths are not installed payloads and
must not exist at their prefix-relative locations. No arbitrary `info/*` allowance,
duplicate/changed/extra/missing auxiliary member or executable undeclared skip. Normal
declared regular/link sets still require exact equality. No source bytes are copied.

Source archive modes0664/0775 normalize by removing group/other-write to the already
protected final0644/0755; that permission normalization does not alter byte identity.
Archive caches have no opt-N variants; enforce the exact observed basename family.
Actual binary delimiter/padding uses the encoding's NUL delimiter (1/2/4bytes), with
raw-zero tail padding preserving length, not an ASCII-only split or inline padding.
These preserve the already-approved source-aware transformation/cache rules rather
than add generic recipes. Dedicated negative fixtures will exercise each narrow rule.
Root fully reviewed and approved these exact three narrow source rules; it independently
read the two original offset74 local-header cases. This is not a protected installation,
host/tool, CLI/provider or model/device admission.

## Conda31 source phase verification and remaining operational gates

The five-path source implementation adds the explicit bounded protected observation,
fixed31 archive-derived transformation/cache/link/licensing ledger, exact four-overlay
mechanical validation and synthetic test fixtures. Protected reads retain before/after
FD/named/ancestor epochs; existing expected-only repeat-read/error behavior is preserved.
Small initially observed metadata is reused once without another byte hash. Overlay
namespaces and known retained Python cache directories are closed using the existing
public file owner; unrelated prefix additions still require the later whole-tree gate.

The tool constructor cleans up its owned child/pipes/selector on setup failure; reads
check the same absolute deadline after select/I/O and before returning. Source-known
metadata values are compared with exact recursive JSON types; bool/float substitutions
for archive/row sizes, build numbers or paths_version fail. Original payload hashes,
declared placeholders/modes, computed final bytes, source/cache headers and resolved
target-owner bytes are checked independently of installed metadata self-attestation.
No archive extraction, bytecode loading/compilation, package-cache trust or repair occurs.

Source gates:145 focused synthetic tests PASS (10.33s),892 model-free tests across the
exact15 suites below PASS (final rerun20.20s), scoped strict mypy4 with
`--follow-imports=silent --explicit-package-bases`, Ruff lint4 and formatting4 PASS.
The focused gate includes a real explicit API CPython `-I -S -B` subprocess importing
the current actual Conda/files/wheel modules, without stubs/Pydantic/schema/Identifiers/ML
imports. Other real test children are bounded synthetic stdlib pipe emitters, not zstd,
an installed successor, wrapper, model or device. Read-only authorized original-archive
diagnostics above remain separately labeled and do not count as installed admission.

Exact regression files (all under `tests/unit/`):

```text
test_embedding_conda_runtime_admission.py
test_embedding_runtime_wheel_closure.py
test_embedding_runtime_bundle_contracts.py
test_embedding_installed_runtime_proof.py
test_embedding_installed_runtime_observer.py
test_embedding_runtime_distribution.py
test_embedding_bundle_resolver.py
test_embedding_offline_backend.py
test_embedding_native_stdio.py
test_embedding_vector_binary.py
test_embedding_incremental_encoding.py
test_embedding_incremental_plan.py
test_embedding_native_runtime_config_contracts.py
test_embedding_native_factory.py
test_embedding_native_entrypoint.py
```

Use explicit `/srv/eom/conda/envs/eom-api/bin/python -m pytest -q` from the repository,
with the existing source roots (repository, Catalog, CatalogContracts, Identifiers,
Protocol, Workflow, Orchestrator, Identity, OperatorIdentity, ContentPack, ItemRegistry,
ContentIntake, HWPX contracts/manager, ImageContracts, WorkflowRunner, ImageProvider,
ImageCandidateRunner, ApplicationAPI/APIContracts). The scoped checker is the explicit
`/srv/eom/conda/envs/eom-core/bin/python -m mypy --strict --follow-imports=silent
--explicit-package-bases` for the three new/changed source Python files and new test;
Ruff check/format uses the same four files. No integration/DB flag is set.

The closed standalone CLI validates only its fixed profile/owner-quarantine argument
shape and the old protected root interpreter/isolation context, then denies missing
independent tool ownership **before** importing any audit module, reading owner inputs
or spawning anything. It cannot load a plugin, accept a Boolean/root-JSON grant or fake
the mandatory tool handle. Parsing the protected local plan/lock inputs and composing
the actual independently accepted tool context remains a later owner gate; the callable
byte-audit operation is implemented and tested, not an operational CLI-success branch.
No receipt/proof is published and the factory admission port is not implemented.

The original installer/new-interpreter history, legacy CPU installation and protected
archives/prefixes remain untouched. Next required work is exact independent host/tool/
loader acceptance, canonical source-list/Conda31 archive materialization via the existing
boundary, full public/private/source/prefix closure and the old-interpreter pre-successor
instruction gate. Only after those gates may root derive actual numerical proofs and
admit fixed factory/launcher/UID/read-only ACLs, complete all GPU-entrypoint/lease/orphan
gates, and run the mandatory real same-input CPU/CUDA benchmark/default activation.
Current status remains CONDA31_SOURCE_ONLY / INSTALLED_NOT_ADMITTED / NOT_PROBED /
CUDA_NOT_ACTIVE. No production or historical state was changed by this source phase.
