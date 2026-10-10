# Fixed isolated CPU experiment runtime

Status: SOURCE IMPLEMENTED / ENVIRONMENT PREPARATION STARTED / PRIVILEGED PUBLICATION AND
ISOLATION NOT_RUN, 2026-10-10 UTC.
This runbook does not approve installation or infer a live PASS from source tests.
The owner design remains [the invocation design](../architecture/ITEM_INFERENCE_TRANSFER_OWNER_INVOCATION_DESIGN.md).

## Fixed boundaries

- Conda prefix: `/opt/eom/conda/envs/eom-embedding-experiment`.
- Model store: `/opt/eom/embedding-models`; reviewed E5-small logical/revision IDs are pinned in
  the installer and typed manifest, not chosen by the worker.
- Owner: existing `eom-workflow-runner`, fixed private workspace under its 0700 home.
- CPU: separate `eom-embedding-experiment` system UID/private group, nologin/no supplementary
  groups, no credentials, sudo, Docker, image, NAS, PostgreSQL or network access.
- Handoff: `/run/eom-embedding-experiments`, root 0750/owner-primary-group. Runtime input/output
  remain root-owned; PID1 supplies only inherited descriptors to CPU.
- Existing `/srv/eom/conda/envs` and API/image/Codex slots are untouched.

The initially observed root-owned eom-web/eom-observe leaves have a developer-writable parent,
so they do not qualify as a protected bootstrap interpreter. No system Python exception is used.

## Responsibilities and trust admission

Developer prepares an explicit Conda `--copy` clone in the fixed new prefix, installs the exact
reviewed CPU lock and non-editable platform wheel, and supplies an independently reviewed complete
byte-tree digest. Root shell/coreutils copies **new inodes** without dereferencing links into a
0700 quarantine, verifies the independent tree hash, checks types/modes/link containment, and verifies
copied installer, wheel, units and polkit bytes against independent approval pins. Only then does it
move the original developer prefix to a retained mutable backup and rename the new root-owned tree
to its original fixed prefix. This ordering prevents compiled Conda/ELF absolute-prefix settings from
loading bytes in the original writable environment. No mutable interpreter, Conda, pip or post-link
is run as root. The first Conda instruction is fixed-prefix `python -I -S -B` running the reviewed
stdlib-only mechanical snapshot helper. It does not load torch, a model, database or credentials.

The helper verifies installed platform payload against the independently reviewed wheel, then its
installed RECORD, and rejects editable installs, escaping links, special/hardlinked members, unsafe
`.pth` and site customization. The one accepted `.pth` is the exact static setuptools distutils shim;
its referenced package bytes also belong to the independently pinned runtime tree. Snapshot SHA
admission is **not** a claim of complete PyPI supply-chain reproducibility: preparation provenance
and dependency source review remain operator responsibilities. `pip check` cannot prove code trust.

Model bytes are read through retained O_NOFOLLOW/O_NONBLOCK directory/file descriptors. The seven
upstream members and manifest raw SHA/size are independently pinned, not trusted from a caller's
manifest. Only exact regular/single-link members are copied, once, to root-only materialization;
group-readable exposure follows full validation. Remote-code loading remains forbidden by the
shared public snapshot validator. Source drift, symlink, FIFO, extra file, bad hash or zero write
fails explicitly. Shared ancestor identity excludes directory-content timestamps/nlink changes,
but the selected source directories and every member retain strict epochs/name identity checks.

## Supported source entrypoints

Preparation is explicit and separate; the installer is not a package manager:

Actual root invocation must use **a root-private copy of the installer script itself**, admitted
against its independently reviewed source SHA before Bash executes it. Do not run a mutable
repository script directly as root. The example private path below is operator-created, root-owned
and 0700; its ancestors and copied bytes require the same no-link/private-copy review.

```text
root:      bash /root/eom-embedding-install-<reviewed-run>/install_experiment_runtime.sh prepare-prefix
developer: /home/eom/miniconda3/bin/conda create --offline --yes --copy \
             --clone <reviewed explicit CPU environment> \
             --prefix /opt/eom/conda/envs/eom-embedding-experiment
developer: install exact infra/conda/eom-embedding-experiment.requirements.lock \
           and reviewed declared platform dependencies, then the non-editable platform wheel
developer: verify python -I imports and pip check; remove stale editable/source hooks
developer: remove group/other write permissions on this fixed prepared prefix only
developer: bash scripts/embedding/install_experiment_runtime.sh fingerprint
reviewer:  independently approve tree SHA, prepared package sources, wheel/helper/unit/polkit SHA
root:      bash /root/eom-embedding-install-<reviewed-run>/install_experiment_runtime.sh publish \
             <runtime-tree-sha> <helper-sha> <platform-wheel> <wheel-sha> <model-source> \
             <prepare-unit-sha> <main-unit-sha> <probe-unit-sha> <polkit-sha>
```

Hashes are 64 lowercase hex digits. Model source must use the reviewed exact logical/revision IDs.
The initially audited temporary numerical environment was not a production installed platform:
it was editable, lacked installed `-I` EOM imports and initially lacked PyMuPDF. These are historical
inventory findings, not claims about its state after operator preparation. Resolve the existing declared
dependencies before taking the reviewed final tree digest. Clone uses `--copy` so ownership changes
cannot alter a shared Conda cache or the original numerical environment. The byte-tree fingerprint
uses sorted NUL-delimited records: `D,path`, `F,path,SHA256`, or `L,path,link-target`; control names,
special files and hardlinks are forbidden. Permissions/ownership and link containment are separately
checked; the full-byte digest is compared on the root-only copy before any interpreter execution.

Source copy commands have fixed timeouts. A timeout creates preserved partial materialization,
not permission to retry a model execution. No model runs or units start during installation.

### Preparation checkpoint and corrected fingerprint

The operator reported fixed-prefix preparation and explicit Conda cloning complete before publish.
The first actual developer fingerprint exposed a Bash definition error: a pipeline outside the
function body defined the function only in a subshell and printed an empty-stream digest. Publication
was not attempted. The corrected function contains its pipeline inside braces; real non-root Bash
regressions verify definition produces no output, a known directory/file/link fixture matches an
independently calculated record SHA, and FIFO/hardlink/control-name fixtures fail. `bash -n` alone
did not cover this runtime semantic defect. Discard the old installer admission SHA and use only
the newly reviewed private copy. A digest from a nonzero fingerprint exit is never an approval pin.
The newly installed platform wheel also revealed PyMuPDF missing in the cloned prefix; the operator
is resolving that existing declared dependency before final `pip check` and tree-SHA admission.

## No-forward privileged smoke

After installation, explicit root invokes:

```text
/opt/eom/conda/envs/eom-embedding-experiment/bin/python -I \
  -m eom_orchestrator.inference_transfer_cpu_installation
```

This checks installed template/polkit bytes and protected ancestry, FragmentPath, no drop-ins,
NeedDaemonReload and the effective systemd main/probe policy. The fixed no-forward probe has the
same main sandbox except its entrypoint/stdin/stdout. Root prepare has separately checked narrow
capabilities and the one writable handoff root. Actual pkcheck subject processes verify main-only
owner start permission and denial of direct prepare/probe, malformed identities, restart and CPU
unit-control access. No generic/transient unit or arbitrary command is exposed.

Only a fresh `eom-embedding-experiment-probe.service` is started. Confirmed terminal/success,
stable InvocationID and post-run policy are required. The CPU process checks actual UID/GID/groups,
NoNewPrivs and empty CapEff/CapBnd; explicit Conda Python/runtime pins and module origins; non-editable
installed RECORD and `pip check`; protected model hashes via the same public validator used by the
backend; actual denied paths/sockets, no GPU, loopback-only network namespace and denied INET socket
creation. Forbidden paths are opened only for denial testing, never read. `ABSENT_IN_SANDBOX` is
reported separately from `DENIED`; absence alone does not prove host permission enforcement.
The probe imports numerical libraries but does **zero model forward/load commands**. Library output
is suppressed and only fixed safe labels are logged. Scientific quality remains NOT_EVALUATED.

## Failure, concurrency and rollback

The installer is single-operator maintenance, not a distributed transaction. Before copying it
requires no loaded experiment/prepare/probe history, including active-exited records. It never
resets failed/terminal units, stops an in-flight run or guesses whether a model ran. The new prefix,
model, unit and polkit steps are not atomically combined; operator must inspect actual phase on
partial failure. Root-private `phase-receipt` records QUARANTINE_COPY, STAGED_NOT_ACTIVATED,
MODEL_AND_WHEEL_VERIFIED and INSTALLED_NOT_PROBED. The backup remains a **mutable original tree**,
not a root-only trusted runtime. Never execute it as root.

Partial quarantines/model directories and the backup are preserved. Normal publish rejects an
existing root-owned installed prefix/model instead of overwriting it. A failed helper leaves the
verified runtime staged but no new units/polkit activation. A later unit-copy failure may have
partially changed installed files; it is not classified as a clean rollback or live success.
Installation does not automatically retry, reset, remove files, restore a mutable environment or
launch inference. Rollback is an explicit operator decision using protected reviewed artifacts,
not a recursive cleanup. Source model and original numerical environment stay unchanged.

Dominant operations are sorted one-time byte-tree admission O(F log F + B), immutable member SHA
checks/copy O(B), fixed map/set membership O(F), and constant installed identity/unit lookups.
There is no persistent vector cache, new registry, database migration, queue or service dependency.
New modules are a removable install/probe adapter; Catalog/Orchestrator core requires no numerical
library unless the optional CPU backend is explicitly constructed.
