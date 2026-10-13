# Native installation admission: same-audit inventory and CPU-first seal

2026-10-13 UTC. DESIGN / PROTOCOL_DRAFT_ONLY / NOT_IMPLEMENTED / NOT_ADMITTED.
Only this note and the two adjacent `.schema.proposal.json` documents are proposed.
They are unregistered ROOTLOCAL evidence, not worker messages, grants or actual receipts.
No production data, prefix, source behavior, resource inventory, unit or default changes.

The current CPU publication failed its OLD whole-prefix audit before NEW; the accepted
read-only wheel diagnosis is not a replacement whole-prefix PASS. That failed input cannot
advance to candidate publication, proof generation, unit probing or final seal. Source
compatibility fixtures cannot change this fact. Root must first review the corrected source
and rerun the actual complete pre-execution audit. Historical failed evidence remains intact.

## Eleven decisions

1. **Boundary.** The existing protected root publisher owns installation evidence;
   Catalog's concrete adapter implements only the existing four-keyword
   `NativeEmbeddingInstallationAdmission.assert_current` port. Installation evidence does
   not authorize an operator, source, Job, INDEX/QUERY purpose, benchmark or service.
2. **Canonical source.** Reuse exact retained archives, accepted source tar and one installed
   prefix. Extend `audit_installed_embedding_prefix` to return its SAME already-checked
   complete tree inventory; do not rebuild the tree through a second parser, copy a prefix,
   duplicate weights or hash archives/payloads for every encode.
3. **Identity.** Use existing configuration logical/revision IDs as the immutable local
   publication key. Keep owner-input raw SHA, audit byte/ELF/source digests, inventory
   raw/semantic SHA, proof/bundle raw/semantic pins, runtime SHA and receipt raw/semantic SHA
   separate. No admission/provider ID, mutable latest marker or permission aggregate.
4. **Resolution.** Actual owner configuration independently pins the final receipt raw SHA
   and the existing four factory pins; JSON cannot supply its own trusted pin. Resolve fixed
   roots from those pins. Check root ownership, mode, nlink, no-follow held/named/ancestor
   epochs, canonical bytes, external bounds, exact schema/semantic/raw closure and profile.
   The unit/owner release must independently accept these pins; parsing is not admission.
5. **Access patterns.** One bounded exact receipt/inventory lookup, ordered immutable entries,
   O(1) member-key membership and per-entry epoch comparisons. Initial audit streams bytes;
   subsequent adapter checks use metadata plus current host/device observations, not full
   hashes. No database, source resolver, queue, network or runtime Git dependency.
6. **Structures.** One frozen prefix inventory, one small sealed receipt and one captured
   concrete adapter. Sorted tuples preserve the existing final audit ordering; a set/map
   checks relative-name uniqueness in O(n), not JSON `uniqueItems` over 100,000 objects.
   The existing host capture remains authoritative; do not copy its private loader parser.
7. **Bounds.** Inventory raw bytes at most8MiB, at most100,000 entries, existing total prefix
   bound16GiB, relative names/links at most512 UTF-8 bytes. Receipt at most32KiB. Depth16,
   integer lexemes at most20 characters, exact integer types before serialization, duplicate
   keys/extra fields/floats/NaN/cycles/constructed bool bypass rejected. Byte bounds are
   enforced before JSON allocation; schema alone cannot impose a serialized-byte limit.
   UTC values also need actual calendar/UTC validation in frozen values; JSON Schema's
   `format` annotation must not silently rely on an absent optional RFC3339 checker.
8. **Concurrency.** Retain the existing root profile-publication reservation across final
   audit, immutable candidate publication, proof read-back, the real unit probe and seal.
   Recheck the SAME prefix/host/archive/bootstrap epochs before each successor instruction
   and immediately before seal. No SQL transaction spans this operation. Host/config/DAC
   changes invalidate capture; perform necessary model ACL changes before final capture.
9. **Dependency ownership.** Initial OLD audit remains admitted stdlib-only `-I -S -B`.
   New frozen models/validation are used only after that gate; Contracts remain IO-free.
   Root owner composes existing public Catalog observers and Orchestrator unit boundaries;
   Catalog must not import API, CLI, private Orchestrator or image internals. No new dependency,
   credential, signing system, privilege routine, registry or daemon is needed.
10. **Failure/replay.** Candidate state is always `CANDIDATE_NOT_ADMITTED`; no candidate can
    satisfy production `assert_current`. Missing, failed, unknown or stale observations
    cannot seal. Reserve immutable outputs O_EXCL, fsync and exact read-back; never truncate,
    repair RECORD/direct_url, overwrite evidence or reuse a failed revision as successful.
    Interrupted evidence remains inspectable. A same-key replay is read-only and still
    requires all current epochs and independently accepted raw pins.
11. **Simpler alternative.** A small self-hashed PASS receipt loses the complete directory/
    symlink epoch closure currently discarded by the audit. Rerunning full archive/hash
    validation per encode wastes work and still cannot prove sandbox/process identity.
    Preserve the authoritative final inventory once, then require actual independent unit
    observations and the existing numerical backend read-back at their respective boundaries.

## Existing seams and the smallest actual gap

`embedding_runtime_prefix_closure.audit_installed_embedding_prefix` already obtains `_tree`
root/directory/regular/symlink nine-integer epochs, exact link targets and verified member
hashes; it checks them after ELF closure and `files.assert_unchanged`/`host.assert_current`.
Its `PrefixRuntimeByteAudit` currently returns only hashes/counts and discards the tree epochs.
Propose an additive frozen `inventory` value returned with that audit: prefix root epoch,
fixed root-ancestor metadata epochs and sorted regular/directory/link entries. It is minted
only at the existing final check, after byte/RECORD/source/ELF ownership closure. A parsed
inventory is never a substitute for the actual audit operation or its current owner context.

Reuse `NumericalRuntimeFileSnapshots`/`open_verified_member` to carry actual initial regular
SHA and subsequent epochs. The original authoritative audit owns complete inventory capture;
do not reach into `_epochs`, `_tree`, `_protected_open` or reconstruct these in a new module.
Ancestor epochs use the existing five-field directory identity, deliberately excluding parent
ctime/size so an unrelated sibling publication is not treated as a changed admitted prefix.
Every in-prefix directory retains its full nine-field epoch to detect added/removed members.

Actual CPU5 proof uses `embedding_numeric_library_versions`, public
`observe_runtime_wheel_installation`/numeric distribution verification, existing proof models
and `ProtectedInstalledEmbeddingRuntimeObserver.verified_proof_metadata`. Share the existing
CPU OS parser through a small public capture seam in `embedding_runtime_os_identity`, not
an expected-device echo. Observe encoder/L2/f32 module hashes through
`observed_embedding_implementation_pins`; full platform/source hashes remain installation
audit, outside the numerical fingerprint. Generate only existing proof/bundle/config values
and validate their public pointer/raw/reference closure, including the unchanged payload.

There is no current public model-free live numerical backend read-back. The backend constructor
configures/checks Torch and immediately loads tokenizer/model; owner code must not call its
private methods, instantiate a model just to claim a no-model probe, or copy the precision rules.
If live recipe read-back is required in the no-forward probe, propose one backend-owned public
`observe_native_runtime_without_model(...) -> EmbeddingNumericalRuntimeDescriptor`, factoring
the SAME existing pre-model installation/import/numerical checks and implementation snapshot.
No flags, second encoder, global cache, model/tokenizer constructor, tensor output or request
descriptor acceptance. Until this seam and actual probe pass, metadata-derived recipe values
are expectations, not measured FP32/thread/capability acceptance. Normal backend read-back and
model/tensor checks remain mandatory before actual encoding; a seal is not inference acceptance.
Factoring this whole-file-pinned backend changes `OFFLINE_ENCODER` raw SHA even if encoding
behavior is unchanged. Freeze/rebuild/accept the actual source and platform wheel first, then
derive new numerical descriptor/bundle/config revisions from the actual installed code. Do not
reuse the previous numerical proof/runtime SHA or touch the historical CPU installed prefix.

## Ordered owner program; no circular production admission

1. Accepted protected OLD bootstrap runs the actual complete audit against the final fixed
   prefix, keeping the publication reservation and its real host/file capture alive. Failure
   stops before any successor instruction. Export the SAME final checked inventory.
2. Root publishes `inventory.json` O_EXCL as `CANDIDATE_NOT_ADMITTED`, validates exact raw and
   semantic read-back and retains all epochs. Candidate existence permits no production factory.
3. Under this root-owned bounded maintenance operation only, after pre-execution revalidation,
   the admitted successor generates/reads back actual CPU5 proof, code identity, bundle and
   config through existing contracts/observer. No worker-provided IDs/hashes, model forward,
   root Torch execution or fabricated device/library observations. The separate actual
   nonprivileged probe performs any optional library import/read-back; OLD/root never does so.
4. Root starts the exact fixed native CPU probe unit, not a developer shell/Python or generic
   command callback. Pin unit/template/probe/effective-policy bytes; bind invocation, PID/start
   time, cgroup and inherited evidence descriptors. Actual worker account/DAC/capabilities,
   denied network/DB/NAS/secret/root-auth/repository/other-worker access and prefix/model writes
   must be independently observed. Loaded ELF maps must close over the admitted prefix/host
   ledger; unknown dynamically loaded members fail. Probe does no model/tokenizer construction
   or forward. Source fixtures/claimed counts/parsed PASS do not establish these observations.
5. Independently observe matching InvocationID terminal status, successful exit, MainPID0 and
   empty exact cgroup/process set; verify unchanged probe output and every candidate/prefix/host/
   config/proof/bundle/code/ACL epoch. Lost process identity, timeout, missing evidence or unknown
   cleanup leaves candidate NOT_ADMITTED; no negative result is rewritten into success.
6. Only the actual root owner then serializes the sealed receipt. Receipt records evidence,
   not an `approved`/`admitted` boolean. Its trusted raw pin is captured separately by the accepted
   installation/owner release. Production adapter construction requires that independently
   accepted pin, current inventory/host capture and matching config/proof/bundle/unit evidence.

This maintenance path is purpose-fixed and unavailable to runtime requests. It does not call
the production factory with a fake successful admission callback to break the seal cycle.
The fixed native probe unit/main and actual root capture are still absent; their implementation
and privileged execution require separate approval. The draft's facts are parsed values only.

## Fixed local layout and current adapter

Proposed immutable evidence root:
`/opt/eom/embedding-runtime-admission/<configuration_id>/<configuration_revision_id>/`.
Names are exactly `inventory.json` and `receipt.json`, derived from existing validated IDs.
No path, executable, authority, optional fallback, role or mutable default occurs in either schema.
Inventory semantic SHA excludes only `inventory_sha256`; receipt semantic SHA excludes only
`receipt_sha256`. Raw SHA always covers complete canonical bytes and remains independently pinned.
Boot identity binds current installation acceptance, not vector-space numerical identity.

Root maintenance reservation/probe outputs stay0700/0600 and are not given to workers.
The worker-side factory cannot reopen those private files. Proposed smallest read composition:
root publishes the SAME nonsecret sealed `inventory.json`/`receipt.json` at this fixed evidence
root with root ownership, nonwritable ancestors, single-link0440 files and narrow read/traverse
ACLs for the exact native UID and existing owner. This is evidence read access only, not worker
write, group membership or authority; do not duplicate an8MiB projection or expose quarantine.
Read-DAC/ACL changes precede final epoch capture. Actual root installation must approve/read back
this recipe; absent readable admitted evidence denies. An inherited-FD alternative would require
separate explicit composition approval; no fourth index FD is silently added here.

`ProtectedNativeEmbeddingInstallationAdmission` privately captures the independently accepted
receipt raw pin and config four-pin identity, bounds/verifies manifests once, and checks the
whole prefix inventory plus protected external host/manifest epochs before/after work. It returns
None on successful current checks and raises stable errors otherwise; no public mint/serializer,
unchecked DTO grant or default. Its `assert_current` signature is unchanged. Its initial read
does not establish first-instruction safety: the protected owner/unit pre-exec check must already
have occurred. No continuously held FD, root-attacker resistance, kernel containment or privilege
admission is inferred from serialized stat epochs or ordinary Python construction provenance.

## Exact next source map for separate approval

- Existing `embedding_runtime_prefix_closure.py` and focused prefix tests: additive SAME-audit
  immutable inventory export, one byte audit; no duplicate archive/tree parser.
- New Catalog `embedding_native_installation_admission.py` and focused unit tests: frozen local
  evidence validation/consumer of the existing four-pin port, bounded protected IO/epoch checks.
- New `scripts/embedding/generate_index_runtime_proof.py` and focused owner-leaf tests: fixed CPU
  maintenance capture/proof publication/seal, protected owner input and actual observation origins.
- Existing `embedding_runtime_os_identity.py` and focused OS tests: one shared CPU capture seam.
- Only if needed, existing `embedding_offline_backend.py` and its focused fake-library tests:
  model-free shared numeric read-back; preserve normal encode cost/behavior and source fingerprint.
- Actual fixed native unit/probe/root capture and read-DAC installation remain explicitly separate
  root/Orchestrator approval. No Catalog-to-API/private-Orchestrator reverse import is proposed.

Next gates cover schema closure/duplicate/bool/UTC/hash/canonical/oversize, forged/changed inventory,
missing/stale receipt/config/profile/root, directory/link/ancestor/boot drift, same-audit export,
single initial byte verification, early/unknown/forged unit seal denial, no model/forward/root ML,
no-clobber interruption/replay, real origin/termination binding and unchanged historical behavior.
Root then runs actual protected disposable/unit negative probes and full read-back; fixtures alone
cannot seal. The initial sealed schema is CPU-only. CUDA installed20-library/device/sandbox,
shared-lease/all-entrypoint/orphan/image gates and its reviewed actual seal successor MUST precede
the real CPU/CUDA benchmark: a candidate cannot execute benchmark/index work. Then the unchanged
actual benchmark correctness/performance/capacity gates precede conditional default activation.
Actual conditional CUDA activation and automatic service identity remain required goal follow-ups,
not displaced or circularly blocked by this source/protocol checkpoint.
