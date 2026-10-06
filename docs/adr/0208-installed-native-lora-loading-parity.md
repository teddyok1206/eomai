# ADR0208: Installed native LoRA loading parity before another style change

2026-10-06 UTC. Diagnostic design, not production activation or quality acceptance.
Overall illustration goal ACTIVE. ADR0207's masked pair reduced exterior scene
transmission but still failed own sparse-ink quality. ADR0206 already has a
source-free balanced100 comparison, which must not be regenerated. Earlier global
blur, control-end0.65 and prompt-only changes were rejected. No new training,
controller sweep, segmentation dependency or data relabeling follows automatically.

## Bounded decision and ownership

Check the actual installed inference LoRA loader against the existing balanced100
adapter before blaming data or changing training. Source inspection finds no
reproduced scaling defect: training and loader both declare rank8/alpha8, the
loader validates all tensor keys/shapes/finite values and sets strength1. Source
inspection is not evidence that every installed tensor reaches the correct PEFT
slot or that enabled numerical projections match the training scaling.

1. Responsibility: opt-in integration diagnostic, not a worker command or a new
   application service. The existing Orchestrator resolves canonical1.6 command
   and all native/support metadata. The isolated numerical role reads the already
   staged immutable metadata/adapter and protected model store. Only the owner
   archives validated small evidence using the existing operations-log contract.
2. Canonical source: the exact completed ADR0207 command, frozen native100 adapter,
   installed lab contract/provider28324e85 and unchanged numerical dependencies.
   No photograph/target/reserved PNG is needed. Reuse the completed workspace as
   read-only input; do not add files or alter its result/history.
3. Identity: pin command logical run/revision/raw SHA and existing adapter/model
   manifests. Stage only a hash-pinned diagnostic script. Script identity and
   operations execution identity are distinct from the completed diffusion run.
4. Resolution: owner canonical existence/lifecycle/schema/media/hash and native
   authority admission precedes role execution. The role uses existing staged
   parsers, FD-bound reads, exact adapter configuration and protected model checks.
   No implicit latest/path-as-identity or direct DB/NAS access.
5. Access: metadata key lookup, keyed PEFT tensors and one streamed digest per base
   parameter before/after loading; a bounded three-projection ordered check. Use
   maps/sets, not repeated name scans or a copied parameter snapshot.
6. Cost: O(metadata + model/adapter bytes), O(parameter-count) small digest map;
   one CPU UNet load and one CPU adapter tensor load. At most three deterministic
   small projection inputs, two CPU threads, six minutes and12GiB host memory.
   No CUDA lease/tensors, diffusion steps, decoded image, optimizer or training.
7. Concurrency: read-only inputs and one exclusively created diagnostic handle.
   Canonical commit reuses existing idempotent owner publication. No model/GPU
   retry, new run key on timeout or modification of historical success/failure.
8. Dependency: test only, public installed provider/PEFT APIs. No new dependency,
   wheel/service/schema/DB/queue change. External libraries remain optional to
   normal source tests; no opt-in means SKIP before importing torch/models.
9. Verification: exact exported adapter key/value equality, every loaded LoRA
   scaling, base-weight digests unchanged, finite/nonzero learned B tensors;
   selected enabled projection = base + scaled B(A(x)), disabling = base.
   Preserve installed dtype rounding when comparing, and report actual error.
10. Failure: preserve the diagnostic terminal log/state; do not patch loader or
    training unless an actual numerical mismatch is reproduced. A timeout is not
    proof of failure and does not authorize restarting the same expensive check.
11. Alternative: trust output pixel differences as proof the loader is correct.
    Insufficient: differences do not prove complete tensor coverage or correct
    scale. Repeating a diffusion pair is more expensive and still indirect.

PASS would close a loader/scaling uncertainty, not establish optimizer correctness,
style learning, semantic fidelity or generalization. If PASS, the next decision
must address the remaining style-learning/photographic-interior question using
the already viewed frozen TRAIN100 and existing failed source-free comparison.
Do not manufacture another identical experiment. Independent blind/HOLDOUT,
population/resource and Item Preview/HWPX activation gates remain separate.
