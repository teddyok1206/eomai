# Protected CPU/CUDA indexing runtime installation — design-only proposal

2026-10-12 UTC. PUBLIC_METADATA_VERIFIED / PROPOSAL_ONLY / NOT_INSTALLED /
NOT_ADMITTED / NOT_ACTIVE / CUDA_NOT_EXECUTED. No installer, Conda/pip, protected
prefix, model, worker identity, service unit, role, DB, GPU, NAS or Git action is
performed by this note or its three proposal locks. Existing experiment runtime,
model manifests and histories stay unchanged.

## Eleven-item boundary

1. **Responsibility/system boundary.** Extend the existing fixed-prefix snapshot
   publication mechanics for exactly `CPU_INDEX_FP32` and `CUDA_INDEX_FP32`.
   Root accepts independently reviewed bytes, not a developer interpreter's claim.
   This installation vertical ends at a protected snapshot, retained raw archives,
   exact package inventory and private source/payload check. Canonical numerical
   proof remains the independent later protected-owner gate. It does not admit a native Workflow,
   manufacture service authority, configure a currently absent CLI/factory, start
   a model or activate a default device. Reuse
   `install_experiment_runtime.sh`'s independent byte-tree hash/quarantine/mode/link
   checks and `_install_experiment_snapshot.py`'s stdlib-only mechanical verifier;
   never call the legacy publish mode against a new prefix.

2. **Canonical source.** One exact raw wheel per SHA under
   `/opt/eom/embedding-runtime-archives/<sha_hex>/<original_wheel_filename>`.
   CPU/CUDA references share common archives, not copies. Installed package bytes
   are the explicit prefix materialization of those archives. One existing
   canonical model payload remains under `/opt/eom/embedding-models`; neither
   prefix copies, links, rewrites or renames its weights/tokenizer/manifest.
   Legacy payload revision/hash and new execution bundle/spec revision/hash remain
   separate. Mutable /tmp prefetch is input evidence, not a protected archive.

3. **Logical/revision model.** Distinguish platform source commit, private platform
   wheel raw SHA, public wheel raw SHA, full prefix byte-tree SHA, lock-graph raw
   SHAs, numerical proof logical/revision IDs and semantic/raw hashes, numerical
   descriptor SHA and execution bundle revision/hash. Source/transport/full-prefix
   hashes are release audit, not numerical-space identity. An unrelated platform
   release must not invalidate numerical encodings when the verified relevant
   implementation/library/recipe descriptor is unchanged.

4. **Required pointers/checks.** Fixed profiles resolve only these locations:

   | Profile | Exact prefix and interpreter |
   |---|---|
   | CPU_INDEX_FP32 | `/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python3.12` |
   | CUDA_INDEX_FP32 | `/opt/eom/conda/envs/eom-embedding-cuda/bin/python3.12` |

   Require CPython3.12.13/Linux x86_64, compatible GLIBC/ELF/loader, independently
   pinned interpreter/full-tree bytes, no external links/hardlinks/special or
   setuid/setgid/group-/other-writable execution members. Reject editable source,
   unknown .pth/sitecustomize/usercustomize hooks and developer-home direct URLs.
   Source includes are a fixed three-lock graph plus the two existing locks;
   pin every child's raw SHA, not merely the outer wrapper. A bare pip -r invocation
   does not enforce comments that pin child locks. The future owner must verify
   the entire graph before deriving its closed local archive map.

5. **Access patterns.** Exact profile/key lookup, deterministic lock/dependency
   deduplication, one ordered archive/member/RECORD audit and atomic no-clobber
   prefix publication. Use maps keyed by normalized distribution name and
   (archive SHA, basename), sets for exact inventory/uniqueness and frozen ordered
   receipts. Same-name repeats must match exact version, URL, raw SHA and selected
   metadata bytes; a conflict is an error, never last-wins. No dependency resolver,
   latest index, fallback flavor, worker-selected path or arbitrary root command.

6. **Structures/indexes.** Existing fixed-prefix shell bootstrap plus a narrow
   fixed-profile stdlib helper branch; no new install manager, DI framework,
   package registry, DB table, queue or search service. Source locks contain
   public direct URL/raw SHA pins; owner installation derives local canonical
   file URIs only after independent raw/archive acceptance. Existing
   embedding-installed-runtime-proof/1.0 remains the numerical contract. Any
   additional machine-readable full-install receipt must have a separate closed
   JSON Schema2020-12/frozen model before behavior; it must not expand the numerical
   proof into arbitrary path/hash permissions.

7. **Scale/complexity.** Shared closure54 public wheels, CPU55 and CUDA70 unique
   public wheels including fixed bootstrap pip/wheel. CPU public archives total
   266,514,328 bytes; CUDA total3,929,095,329 bytes. Private platform/lease and
   Conda-base/archive/installed/temp overhead are excluded from these totals.
   Dedup/marker closure is O(D+E); streamed copy/hash/member audit is
   O(total archive + installed bytes + ZIP entries). Reuse existing bounded ZIP
   gate before allocating ZipFile objects and existing numerical proof limits:
   <=20,000 entries/wheel, bounded central directory, <=2 GiB raw/member and
   <=4 GiB declared expansion/wheel. Do not silently reuse the old platform-only
   10,000-entry/64-MiB-member bounds for Torch. No wheel/model bytes enter Git,
   DTOs, DB or logs. Prefix filesystem capacity is measured before staging,
   separately from compressed archive budget.

8. **Transaction/concurrency.** No DB transaction. A root-owned fixed-profile
   installation exclusion/no-clobber guard fences the target; known active,
   terminal or uncertain unit/workspace identities are evidence, not resettable
   installation state. Root copies developer input without following source links,
   takes an independently approved byte-tree hash of root-private quarantine,
   rejects escaping links/unsafe modes, then publishes the root-owned snapshot
   at its exact final prefix before its first interpreter instruction. This
   preserves absolute Conda/ELF prefix references without reaching developer bytes.
   Never execute developer Conda, pip, post-link, site or Python as root; no staged
   helper/interpreter runs before independent hash + ownership/link/mode checks.
   Failed/staged-not-admitted state retains bounded phase evidence and is not
   silently retried, overwritten or labeled active.

9. **Dependency/ownership.** Developer assembly (later, non-root) uses only the
   fixed exact Conda base and owner-accepted offline wheel inputs. Root bootstrap
   uses /usr/bin:/bin and clears Python/loader/shell injection variables. Its first
   interpreter is exact bin/python3.12 with -I -S -B and a separately raw-pinned
   root-private stdlib helper. Root does not install packages or import ML.
   Package installation is complete before quarantine; root verifies it.
   Any later protected contract/observer checks import only independently
   verified protected code, use -I -B/PYTHONDONTWRITEBYTECODE, and do not construct
   the backend/load a model. Full-prefix/ABI/environment/systemd audit and the
   numerical observer are independent owner gates; neither substitutes for the
   other. Catalog/IAM/Runner purpose/service admission remains separate.

10. **Failure/retry/idempotency.** Missing private build pin, incomplete closure,
    unexpected distribution, raw/member/RECORD mismatch, wrapper/direct-URL
    mismatch, unsafe archive/FD/ancestor/prefix, source drift, broken symlink,
    insufficient capacity or target-existing fail explicitly. Never infer raw
    wheel identity from version, Conda metadata or installed RECORD. No automatic
    download/repair, flavor switch, root permission widening, legacy-prefix
    mutation or identity reset. Same accepted archive may be referenced by both
    profiles; a new protected prefix/proof is a reviewed immutable admission,
    not replaying a model or relabeling historical CPU evidence.

11. **Simpler alternative and tests.** Upgrading the old CPU prefix or copying its
    entire installed site also carries unrelated development/API extras, replaces
    history and cannot demonstrate the new installed code. Executing root pip on
    developer site crosses the bootstrap trust boundary. Reuse the existing
    snapshot-first mechanics with exact new fixed targets; test legacy modes
    unchanged, no execution before hash/mode/link checks, include/closure conflicts,
    wrong Python/prefix, stale source, archive/member/RECORD/generated-file denial,
    no-clobber/concurrent publication and staged failure preservation. Synthetic
    source gates precede opt-in owner installation; actual CPU/CUDA import,
    physical lease/device isolation, numerical comparison and default activation
    remain later gates, not metadata PASS.

## Exact dependency proposal and evidence

- [Shared proposal](../../infra/conda/eom-embedding-protected-runtime.requirements.proposal.lock)
  references [common numerical4](../../scripts/embedding/common-numeric-runtime-wheels.lock)
  rather than repeat their URL/hash bytes; it adds50 exact public direct references.
- [CPU wrapper](../../infra/conda/eom-embedding-index-cpu.requirements.proposal.lock)
  references shared54 and adds only torch2.7.1+cpu with the existing raw pin.
- [CUDA wrapper](../../infra/conda/eom-embedding-cuda.requirements.proposal.lock)
  references shared54 and [existing CUDA25](../../scripts/embedding/cuda-runtime-wheels.lock).
  Their nine common name/version/URL/raw SHA/metadata pins are identical, yielding70,
  not79, public archives.

The existing root-prefetched inputs are CUDA25 at
/tmp/eom-embedding-cuda-wheels.u9WOCG9U (3,848,835,734 bytes), common4 at
/tmp/eom-embedding-common-wheels.SV0yGxFN (32,014,410 bytes), and CPU Torch at
/tmp/eom-embedding-cpu-wheel.8TJStOlK (175,833,687 bytes). Their separately recorded
raw/ZIP inspection results stay historical evidence; this task performed only
small-metadata checks and does not relabel them as execution of a new installer.
The full shared54 closure has41 additional public archive candidates totaling
48,245,185 bytes not present in those three batches. They remain NOT_PREFETCHED /
RAW_BYTES_NOT_VERIFIED here; no installer may synthesize their presence from
matching historical installed metadata. Private build archives are additional.

The deterministic read-only include-map check reports CPU PUBLIC_CLOSURE_PASS55
and CUDA PUBLIC_CLOSURE_PASS70. It recursively resolves only these fixed source
includes, rejects differing same-name tuples, matches each unique selected
name/version/URL/raw SHA to reviewed small metadata, and checks every active
specifier/marker with required binary/argon2 extras. It neither resolves a new
version nor downloads/installs an archive. Reviewed lock graph raw pins:

| Source lock | Raw SHA-256 |
|---|---|
| Shared54 proposal | `974df998a3267b28fa4eadf54d69e7e14379e0b9e84683ab3bbca92d21cd5b04` |
| CPU55 proposal wrapper | `03b70b785820cdf61889690da2c82f8fb4a4560e5ea8034c4b647d55088ac71b` |
| CUDA70 proposal wrapper | `1adaf2109971b4ed1eb23d7c5400a76ea59a06c2a9d059ba54a493ec33b52784` |
| Existing common4 | `e2278a6253cd092c340091d08e5d20283e3a1e5052316c010c4c3cd12440513d` |
| Existing CUDA25 | `1c1bf705f0a0af11f30ee669b870a60a786d3faa344b62fe2bc2095d1fd464ba` |

This 2026-10-12 read-only metadata check preserved all model/protocol versions from
the existing CPU requirements and all additional actual platform base versions.
All54 selected non-yanked PyPI wheel metadata documents (591,883 bytes) match the
protected historical CPU METADATA/PKG-INFO byte-for-byte. Each direct reference
pins the exact official version-specific wheel URL/raw SHA and its comment pins
the small METADATA SHA/declared archive size. The metadata source is that exact
wheel URL plus .metadata; release selection used
[PyPI's version-specific JSON endpoint](https://docs.pypi.org/api/json/#get-a-release),
not latest. Matching metadata is NOT archive-body, installed-file, RECORD, CVE,
ABI or activation proof. No wheel body was downloaded in this task.

Fresh small metadata checks additionally preserve the exact CPU Torch metadata
SHA0464be2f825052a9766185210a6143fbde6762d77cffd1a77d2f8326baf12ae5
and CUDA Torch metadata SHA
e41a1ec38ccc8170c228b57b1432cc7ae03718dd69bb0a72d1fc32707dde1765;
the official CPU/cu128 wheel URLs and raw SHA pins stay unchanged. This task also
checked all25 CUDA small metadata identities and the nine repeated pins; full
public marker/specifier closure uses Python3.12/Linux/x86_64 and only required
psycopg[binary]/pwdlib[argon2] extras inherited from platform base requirements.

| Inclusion reason | Exact packages/versions (all separately raw-pinned in locks) |
|---|---|
| Shared numerical libraries | numpy2.4.6; safetensors0.6.2; tokenizers0.22.2; transformers4.56.2 |
| Torch base/transitive | filelock3.32.3; typing-extensions4.16.0; setuptools83.0.0; sympy1.14.0; networkx3.6.1; jinja2 3.1.6; fsspec2026.7.0; mpmath1.3.0; markupsafe3.0.3 |
| Transformers/tokenizers/Hub | huggingface-hub0.35.3; hf-xet1.7.0; packaging26.2; pyyaml6.0.3; regex2026.9.3; requests2.34.2; tqdm4.70.0 |
| Requests base transport, not network permission | certifi2026.7.22; charset-normalizer3.5.1; idna3.19; urllib3 2.7.0 |
| Protocol/schema | annotated-types0.8.0; attrs26.1.0; jsonschema4.26.0; jsonschema-specifications2025.9.1; pydantic2.13.4; pydantic-core2.46.4; referencing0.37.0; rpds-py2026.6.3; typing-inspection0.4.4 |
| Actual platform base persistence/PDF | alembic1.19.1; mako1.4.1; sqlalchemy2.0.52; greenlet3.5.5; psycopg3.3.4; psycopg-binary3.3.4; pymupdf1.26.7 |
| Actual platform pwdlib[argon2] | pwdlib0.3.1; argon2-cffi25.1.0; argon2-cffi-bindings25.1.0; cffi2.1.1; pycparser3.0 |
| Actual platform CLI base | typer0.27.1; shellingham1.5.4; rich15.0.0; annotated-doc0.0.5; markdown-it-py4.2.0; mdurl0.1.2; pygments2.20.0 |
| Fixed bootstrap, not developer extras | pip26.1.2; wheel0.47.0; the already listed setuptools/packaging |
| CUDA-only numerical/runtime | exact NVIDIA14 + triton3.3.1 in existing CUDA lock; not compile/distributed/GDS permission |

Platform base libraries are included because the current platform wheel declares
them, NOT because the encoder may access PostgreSQL, NAS, PDF documents, IAM or
services. Exclude historical FastAPI/Starlette/Uvicorn/httpx/httpcore/anyio,
pytest/mypy/Ruff/type stubs and unrelated extras, API contracts, torchvision,
torchaudio, scipy, pandas, sentence-transformers, accelerate and external LLM clients.
Typer0.27.1 has no active Click requirement; do not copy historical Click merely
because it is installed. Setuptools vendored members are its own archive payload,
not additional top-level installed distributions.

### Private wheel acceptance is still pending

There is no accepted current eom-platform0.1.0 wheel containing the frozen native
request/owner/backend/proof leaves. Root must build from an exact accepted Git
archive after the required leaves are frozen, pin that commit/archive/build and
wheel raw SHA, and independently verify source/payload/RECORD under quarantine.
A worktree build, version string or historical platform wheel is not a substitute.
New METADATA must retain the reviewed exact base closure; only CUDA's explicitly
selected gpu-runtime extra may require eom-gpu-lease0.1.0.

The earlier non-root lease candidate is
/tmp/eom-gpu-lease-wheel.jvzfDpXy/dist/eom_gpu_lease-0.1.0-py3-none-any.whl,
4,456 bytes/raw SHA
5d7ee6850447871dec556c21e1a16f3822e0748fa4ab6052a19cbd3184fbef89,
source cdb8cb83. This is provenance, NOT root archive/RECORD/quarantine acceptance.
A fresh reviewed private lease wheel/source pin remains required for CUDA.
The public proposal locks intentionally contain no invented private raw SHA.
Any installer must refuse until those exact private inputs and the include graph
are independently admitted; installing public dependencies alone is not a full
EOM runtime.

## Concrete snapshot/admission sequence — proposed, not run

1. Root reviews exact lock graph/raw SHAs, source/build/private wheel pins,
   Conda-base candidate and finite storage budget. Retain exactly one root-owned
   no-clobber raw archive per SHA; hash/copy via held no-follow descriptors with
   named/FD epochs, inspect safe ZIP/RECORD/metadata closure before exposure.
   Public archives/proofs may be root-owned0755 ancestors/read-only0644 files;
   no write/create authority is granted to runtime users.
2. A dedicated non-root developer assembly phase prepares a NEW exact final prefix,
   installs only verified local archive URIs with explicit bin/python3.12,
   --no-index --no-deps --only-binary=:all: --require-hashes --no-compile, and
   disables bytecode/site customizations. Direct URL requirements can still access
   the network despite --no-index: do NOT feed public HTTPS proposal locks directly
   to installation. The owner derives only closed local file URI/hash references.
   No Conda/pip or post-link runs as root. No mutable old CPU site is cloned.
3. Verify independently reviewed runtime tree/helper/input pins in root quarantine
   using the existing shell bootstrap. Preserve target absence/phase evidence.
   Replace only the selected developer NEW prefix with its root-owned snapshot,
   leaving the historical experiment prefix and units untouched. Resolve every
   execution link inside that snapshot before exact bin/python3.12 -I -S -B runs.
4. The raw-pinned stdlib helper validates the complete package/RECORD/archive
   closure, exact distribution inventory and root protection. Initial numerical
   proof must raw-pin actual installed RECORD bytes and closed generated additions,
   not copy a planned record hash or version echo. Python version/interpreter/full
   prefix/Conda/GLIBC/ELF audit is separate and explicit.
5. Produce canonical existing installed-runtime-proof1.0 for CPU5 only after
   independent closure and actual CPU read-back. CUDA20 proof/admission additionally
   waits for the separate actual owner physical capture/ownership gate; the
   bootstrap must not fabricate capability, UUID/PCI/boot/driver evidence or
   acquire a GPU just to mark installation successful. Preserve raw vs semantic
   hash; publish under no-clobber proof ID/revision. Installer receipt records full
   audit and root review separately. Actual observer read-back uses the selected
   prefix interpreter and current physical ownership where needed. Do not run the
   backend, load weights or touch GPU in this installation vertical.
6. End INSTALLED_NOT_ADMITTED/NOT_PROBED. Only separately reviewed native factory,
   fixed isolated launcher/stdio, model read-DAC, current Catalog/IAM authority,
   Runner service-purpose, GPU lease/device/cleanup and numerical gates can advance
   admission. GPU comparison/default activation is already part of the approved
   goal, not grounds for a redundant user approval request.

### Preserve actual installer additions; never rewrite evidence to fit

Install from the retained canonical archive URI before generating proof so that
direct_url.json names that archive, not a /tmp/quarantine/developer path.
For each numeric distribution preserve and raw-pin actual installed RECORD plus
only INSTALLER=pip newline, optional zero-byte REQUESTED, the closed exact
archive_info hash/hashes direct URL forms, and fixed console wrappers derived from
verified entry_points.txt. Their shebang is EXACT selected bin/python3.12, not
bin/python, /usr/bin/env or a source interpreter. The observer supports two explicit
distlib wrapper byte recipes; actual pip26.1.2 output must match one or installation
fails explicitly. Do not edit wrapper/RECORD/direct-URL bytes to fabricate acceptance.
--no-compile/-B prevents new pyc; unexpected package bytecode/hooks fail closed.
Torch's declared torchfrtrace target is absent in the accepted upstream archive;
its unused wrapper may be proven as generated bytes but must never be executed or
reported as a working CLI. Shared identical NVIDIA namespace members are exact
references; differing bytes remain a collision error.

Canonical model read-DAC remains a separate security gate. New users do not silently
join eom, the old CPU group, sudo or Docker or inherit legacy workspace access.
A narrowly reviewed read-only per-UID ACL on exact payload/ancestors could preserve
payload content/hash without copying it, but changes ACL/ctime evidence and must be
explicitly reviewed/read back; it is NOT performed or granted here. No model
permission or legacy metadata mutation is hidden inside package installation.

## Bounded source paths for the next reviewed implementation

Propose only scripts/embedding/install_index_runtime.sh (new fixed two-profile root
bootstrap) and an additive index-runtime branch in
scripts/embedding/_install_experiment_snapshot.py, plus focused synthetic installer
tests and this note/three proposal locks. Preserve the existing install_experiment
shell and every legacy helper command/constant/behavior. Do not generalize arbitrary
prefixes, executable selection, include paths, wheel counts or root subcommands.
The new shell reuses the snapshot-first mechanics; the helper reuses existing
root/FD/tree/hash and private platform payload/RECORD checks. It does not copy the
authoritative numerical archive/installed-member verifier or generate a proof.
The existing numerical observer and proof schema remain the independent owner gate
after exact protected code admission; installation status is not numerical/ABI proof.

Full numerical observer source is already implemented; configured installed native
CLI/factory and fixed CPU/CUDA launcher/composition are not. No source design is an
installed package, no archive inspection is an installed proof, and no protected
prefix is a source/service/GPU permission grant.

## Exact Conda-base candidate — declared metadata, not raw acceptance

### Owner public-archive retention before wheel assembly

Actual phase-order review found that canonical `direct_url.json` requires retained public
archive URIs before non-root pip assembly; post-snapshot retention alone cannot supply them.
The narrow additional `index-public-archives` helper entry is reviewed for this prerequisite:

1. Responsibility: retain only the same fixed CPU55/CUDA70 public archives before assembly;
   not package installation, source authority, native admission or numerical proof.
2. Canonical source: one existing raw archive per SHA/basename; never duplicate it per prefix.
3. Identity: exact profile, fixed five-lock hashes and raw archive hashes remain separate.
4. Resolution: reuse no-follow/held FD/owner/epoch/size/hash/no-clobber retention checks;
   no executable, model, private-wheel, URI or include selection from a worker.
5. Access: one bounded dependency-name map plus sorted archive iteration, no solver/network.
6. Structure: reuse the existing lock and retention functions; one shared wheelhouse-map
   function serves pre-assembly retention and final snapshot verification.
7. Cost: O(archive bytes + fixed inventory), CPU266,514,328/CUDA3,929,095,329 bytes.
8. Transaction: no DB; incomplete raw-copy reservations remain private/refused on replay.
9. Ownership: root invokes a raw-pinned root-private helper with the already protected
   `/opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12 -I -S -B`,
   CPython3.12.13/Linux/x86_64, read-only; no legacy environment/model/unit changes.
   It cannot execute a still-developer-owned indexing interpreter or import installed ML.
10. Failure: wrong context, lock/source/inventory/hash drift or partial reservation fails;
    no download/repair, identity reset, model/default change or installation PASS.
11. Simpler alternative: installing from /tmp then editing direct-URL evidence would forge
    provenance. Reusing this small bootstrap leaf is smaller than a second archive manager.

The final snapshot branch remains independent and retains/rechecks the same raw archives.
New public-cache ancestry is explicitly published0755 after creation under root's private
umask077. An existing wrong-mode root or incomplete SHA reservation fails without repair;
reviewed operational recovery preserves the failed reservation before a bounded retry.
Private current-source wheel acceptance, full-prefix/ABI, actual numerical observer and
runtime/device/source gates remain required. Public retention is not archive-member/RECORD
acceptance or protected runtime installation.

Read-only historical conda-meta contains31 exact records. Python3.12.13 build
hc5f7cf0_3 requires pip; pip26.1.2 build pyhc872135_0 requires setuptools and wheel;
wheel0.47.0 Conda requires packaging>=26.0. Shared public54 therefore includes exact
pip/wheel/setuptools/packaging, not arbitrary developer build extras.
The selected31 base candidates below fix versions/builds/URLs/SHA claims instead of
running conda create against current latest defaults. Their declared source SHA is
NOT independent raw-byte acceptance. Root must independently accept the actual
base/full-tree/loader bytes and resulting distribution inventory before execution.
Any overlapping Conda and wheel installation provenance/overwritten members must
be explicitly audited; two metadata claims do not create two canonical package
copies or waive the actual final installed-file proof.

## Follow-up source implementation and preserved evidence

The approved bounded implementation adds only the new fixed-profile shell and
`index-runtime` branch in the existing stdlib helper. Legacy shell bytes and every
legacy helper function/constant AST remain regression-pinned. The shell's fixed
root publication lock, independently approved tree/helper hashes and link/mode
checks precede the exact protected `bin/python3.12 -I -S -B` instruction. Inputs are
bounded CLI fields; receipts contain phase/status/source-pin lines, not new JSON.
No models, ACLs, groups, units, factory or proof are installed/generated by this leaf.

The helper requires all five actual lock raw pins and exact shared54/CPU55/CUDA70
inventory, then retains only the selected public archives plus required private
wheel and source tar archives. A SHA directory is reserved0700 and exposes its
single0644 root-owned/nlink1 archive only after streamed raw-hash/epoch acceptance.
Interrupted or mismatched reservations remain private evidence and cannot be
reset/overwritten by another invocation. Existing complete exact archives are
verified/referenced rather than copied. Private platform/lease input requires raw
wheel SHA, full40-character commit and raw Git source-tar SHA; Git archive comment
must match that commit and current native/owner/proof source leaves must match
both wheel and installed bytes. Historical platform substitutes therefore fail.
Numerical archive/RECORD/console/direct-URL validation is not copied into this
bootstrap: the existing protected numerical observer remains a separate owner gate.
Full prefix/ABI/Conda member provenance likewise remains explicit independent audit.

`publish PROFILE` has exactly12 fixed fields before1–4 public wheelhouse directories:
runtime tree SHA, helper SHA, platform wheel path/SHA/commit/source-tar path/SHA,
lease wheel path/SHA/commit/source-tar path/SHA. CPU requires all five lease fields
to be literal `-`; CUDA requires exact nonempty pins. No arbitrary prefix/command
selector is accepted. The helper verifies root/isolated/no-site/no-bytecode context,
exact interpreter pathname and CPython3.12.13/Linux/x86_64 before archive writes.
It ends `INSTALLED_NOT_ADMITTED / NOT_PROBED / OWNER_GATE_REQUIRED`, never ACTIVE.

The earlier reviewed shared lock8ba57e4018522c99d1484d30874b885ee02f80202bdc7f882aa9f5f468b69835
became974df998a3267b28fa4eadf54d69e7e14379e0b9e84683ab3bbca92d21cd5b04
only because the header clarified “no extras” to “no unrequested extras”. CPU
b233b21d421504d2a26ccad782335e276281b30d071ad939f5f398d99efb5e63
and CUDAa19bea2a95acaba34d027bf1a124c716cda96ba1e2d2d6e8f00df6290245812d
changed to the current table pins only by updating their shared-child raw-pin comments.
All URLs, versions, raw archive SHA pins, requirement and include rows are unchanged.
The actual helper verifies the final table pins, not the historical comment bytes.

After the metadata-only phase above, root independently prefetched/verified the
additional41 candidates (48,245,185 bytes) under
`/tmp/eom-embedding-runtime-dependency-prefetch.oCqtBc7F/wheels`, derived from the
historical shared8ba57 lock. That actual raw-byte PASS is a separate follow-up;
the earlier NOT_PREFETCHED/RAW_NOT_VERIFIED metadata phase and original receipts
are not relabeled. No package/prefix installation or numerical/GPU execution
was performed by that prefetch or this source implementation.

Root subsequently prefetched the exact31 declared Conda base archives under
`/tmp/eom-embedding-conda-base-prefetch.KoqIDSXB`:31 independent raw-SHA and
before/after leaf-epoch checks PASS,56,222,902 bytes. The outside-Git fixed
sources.lock remains historical evidence. No extraction, installation, protected
runtime, model or GPU operation was part of that check. Full base member/full-tree/
ABI admission is still pending; these actual archive bytes do not prove the prefix.

Source gates for this bounded bootstrap are255 PASS across new installer19 tests
and historical CPU installation/systemd/stdio suites; Ruff format/lint and strict
mypy PASS on helper+tests, and bash syntax PASS on the new shell. New tests cover
exact real55/70 lock graph, raw retention/reuse/no-clobber, missing/changed/linked
inputs, bounded failure and interrupted private reservation, FD-stat/close cleanup,
source commit/current leaf/historical wheel mismatch, exact inventory/extra denial,
mandatory private source pins/nonroot context, snapshot hash-before-execution,
interrupted prefix replacement and independent-process publication-lock denial.
Temporary shell tests substitute only test paths/UID checks and an inert interpreter;
they are not real root/bootstrap/interpreter/ABI/installed numerical acceptance.
Legacy shell raw bytes and all legacy helper function/constant AST are pinned.
No protected runtime, package/model install, root, service, database, network/GPU
or Git action was executed by these source tests. Native factory and actual owner
numerical/full-prefix/authority/device admission remain explicitly pending.

### Additive private-wheel preallocation hardening

Root review identified that the historical platform wheel validator constructs
`ZipFile` before checking its member count. That historical function stays unchanged.
The new index-only stdlib bootstrap now scans ZIP32 EOCD, actual central headers,
local-header/name/size closure and bounded extra fields before either private
`ZipFile` construction or the legacy platform validator. The retained raw cap is
64MiB; actual entries are at most10,000 and central bytes at most8MiB. ZIP64,
multidisk, archive/member comments, malformed/truncated headers or extra fields,
encryption and mismatched counts/offsets fail before an untrusted member inventory
is allocated. The scan is O(entries + central bytes), with one bounded header/name/
extra-field allocation at a time. This self-contained bootstrap leaf is necessary
because protected numerical/archive-owner packages are not admitted for import yet;
it does not replace their later authoritative archive/numerical proof.

Private wheel `.pyc` members are denied. Before the final installation-only status,
the installed tree denies registered or unregistered `.pyc` (including unchecked
`__pycache__`) in all `eom_*`/`eomctl` namespaces, limits their combined entries to
20,000, and rejects private namespace links so an internal link cannot bypass that
scan. Public dependency caches remain a separate numerical-owner admission concern.
Both CPU platform and CUDA platform/lease archives receive the same preflight;
the standalone source-leaf checker also preflights before its own `ZipFile`.

Follow-up source gates:299 PASS across the current installer39 and historical CPU
installation/systemd/native-stdio suites, Ruff format/lint PASS, strict mypy PASS
on helper+tests, and new shell bash syntax PASS. Added synthetic cases prove declared
and actual10,001-entry denial before any `ZipFile` constructor, exact10,000 acceptance,
central-byte bound, ZIP64/multidisk/comment/malformed denial, private/unregistered
bytecode and internal-link refusal, and check-before-status ordering. Historical
255-pass evidence above is not relabeled. New helper raw SHA is
`f8c35aa1b97e4915045b2efb17e1154dbd882830fe920ff90e8a53248b22f5b1`;
the shell remains
`12ece6628dd6faccb3564d701b8349a86b51ef9790fbfb02f2c0754665c0e682`.
No real installation, root, package/model/GPU execution or admission occurred.

| Exact name/version/build | Declared official archive URL | Declared raw SHA-256 |
|---|---|---|
| _libgcc_mutex 0.1 main | [archive](https://repo.anaconda.com/pkgs/main/linux-64/_libgcc_mutex-0.1-main.conda) | `476626712f60e5ef0fe04c354727152b1ee5285d57ccd3575c7be930122bd051` |
| _openmp_mutex 5.1 52_gnu | [archive](https://repo.anaconda.com/pkgs/main/linux-64/_openmp_mutex-5.1-52_gnu.conda) | `2f2c16a33f51ba032e8d4929b4d2e9173d81931d8d280a4a4a85a2412e8bdaf0` |
| bzip2 1.0.8 h5eee18b_6 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/bzip2-1.0.8-h5eee18b_6.conda) | `235f266d5f9c3c61748bb1af0eff21bc7ed2a2a356b97ff28d9c1135039b08b0` |
| ca-certificates 2026.7.16 h06a4308_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/ca-certificates-2026.7.16-h06a4308_0.conda) | `0592253999d0ad906a99078132fe2b1c1885ac1210c9104fd29dd23b3f7b475d` |
| ld_impl_linux-64 2.44 h9e0c5a2_3 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/ld_impl_linux-64-2.44-h9e0c5a2_3.conda) | `4a4875ab4354d4a1bf1695850efad8787d7063387ed6b5aec5ecb659869e2590` |
| libexpat 2.8.2 h7354ed3_1 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libexpat-2.8.2-h7354ed3_1.conda) | `47ace47583058a92cd32f2ad8016b89a219a53fcf38bb11428e89d4e6aa5ddc1` |
| libffi 3.4.8 h06d3fd0_3 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libffi-3.4.8-h06d3fd0_3.conda) | `d000d5d1843f472c7c8f750af2113013c74e9dcdcbe58220568d9d37df5a8607` |
| libgcc 15.2.0 h69a1729_8 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libgcc-15.2.0-h69a1729_8.conda) | `10fbca6e0cc0da1018f82f3c92e3841e734e704dbfee5df88ae652a49d8b402f` |
| libgcc-ng 15.2.0 h166f726_8 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libgcc-ng-15.2.0-h166f726_8.conda) | `3b4b734309a58b3ded42e01aecfbb91b029ad22d768a4c9f0f4f0006a3172203` |
| libstdcxx 15.2.0 h39759b7_8 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libstdcxx-15.2.0-h39759b7_8.conda) | `30b7a96c0f1f527d16ec9ec7f80404f34d4b916332cca0634111ed077d7fc870` |
| libuuid 1.41.5 h5eee18b_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libuuid-1.41.5-h5eee18b_0.conda) | `2a401aafabac51b7736cfe12d2ab205d29052640ea8183253c9d0a8e7ed0d49a` |
| libxcb 1.17.0 h9b100fa_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libxcb-1.17.0-h9b100fa_0.conda) | `f9cd1564fc83261ddba7496404f18143d4f8fda52e42c040005c1b1ad3e47f56` |
| libzlib 1.3.2 h47b2149_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/libzlib-1.3.2-h47b2149_0.conda) | `02b0d3bad12d15c668f06a32283907608bcfb49ca40d9d09d3bcfe6bd4765f31` |
| ncurses 6.5 h7934f7d_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/ncurses-6.5-h7934f7d_0.conda) | `5ab33c1e90efbb3507116ae00d1f6740ec74104bb7028dc017f5f76796cee154` |
| openssl 3.5.7 h1b28b03_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/openssl-3.5.7-h1b28b03_0.conda) | `dc81e47be134c1449a1232ace2af3688f7b61666717bc90a25deadc152d6344c` |
| packaging 26.2 py312h06a4308_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/packaging-26.2-py312h06a4308_0.conda) | `ab3a6f40ba97fb23edb6760d3698ae7038294f81d5ee248af21695ae9b6d92a2` |
| pip 26.1.2 pyhc872135_0 | [archive](https://repo.anaconda.com/pkgs/main/noarch/pip-26.1.2-pyhc872135_0.conda) | `fe4396e88d44b9df60ebc911505b3902d0754439c2cf4fc0d2c6bfc281ee05e8` |
| pthread-stubs 0.3 h47b2149_2 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/pthread-stubs-0.3-h47b2149_2.conda) | `f9ccf45615a75712116b79a4b02fbc69e681b4e82d65a0dd11430fac3244623c` |
| python 3.12.13 hc5f7cf0_3 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/python-3.12.13-hc5f7cf0_3.conda) | `23572134eb5b0c89673831ceb575c883425039c01778fcaed5ebf5cc513e2a84` |
| readline 8.3 hc2a1206_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/readline-8.3-hc2a1206_0.conda) | `0a438fa74f2776bde137017d6c18214b5da65b557f6a59f877fa4e091582f789` |
| setuptools 83.0.0 py312h06a4308_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/setuptools-83.0.0-py312h06a4308_0.conda) | `5770655e4b0f955196aa85bf81b5b79bccc8f87d25c27831551f589e5ba5b669` |
| sqlite 3.53.2 h795bf6d_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/sqlite-3.53.2-h795bf6d_0.conda) | `e096790542919a5981c9ad025c5e9b205d9fab274a5ae8fb5847a7fed341d828` |
| tk 8.6.15 h54e0aa7_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/tk-8.6.15-h54e0aa7_0.conda) | `a3bcd301ddd0bdb2f52f9bd3274fabe3c33d43ed61e58ee657efeac01b4be157` |
| tzdata 2026c he532380_0 | [archive](https://repo.anaconda.com/pkgs/main/noarch/tzdata-2026c-he532380_0.conda) | `52adc4b0a9cce2ffb8ad319d54b7c940ae7961f7caf7ce6851eec4b3f542c368` |
| wheel 0.47.0 py312h06a4308_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/wheel-0.47.0-py312h06a4308_0.conda) | `a93e5a2f4aa6b0585f240cb9896e7d1e1962cc551980d7824d13efdfdb71ab05` |
| xorg-libx11 1.8.12 h9b100fa_1 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/xorg-libx11-1.8.12-h9b100fa_1.conda) | `e9e6228687c03d1c1318f6d7434e6c54f1a5e821def15d4926a5ce4c0a01a17e` |
| xorg-libxau 1.0.12 h9b100fa_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/xorg-libxau-1.0.12-h9b100fa_0.conda) | `68acf87da69a0237d5083798a9cc9b89d2887a84a5323aa740006b53cd5159ef` |
| xorg-libxdmcp 1.1.5 h9b100fa_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/xorg-libxdmcp-1.1.5-h9b100fa_0.conda) | `459c8497d1c22b020404b481fa12011abeb27d8eefde37dd4ac9f5a443fd5ac7` |
| xorg-xorgproto 2024.1 h47b2149_2 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/xorg-xorgproto-2024.1-h47b2149_2.conda) | `7e6df766a22cd209e572097f5f4b0ab63b2277143a32b8ee66d5a147051f86d0` |
| xz 5.8.2 h448239c_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/xz-5.8.2-h448239c_0.conda) | `6394c59cbb6ff035f3a5e4d599a32214cb304b362299fd40be39d7ed20bef9d1` |
| zlib 1.3.2 h47b2149_0 | [archive](https://repo.anaconda.com/pkgs/main/linux-64/zlib-1.3.2-h47b2149_0.conda) | `4bb61142e8fe22510086c1030e1ff3ad4888ebf9bf0a11e9931594e8549a9d42` |
