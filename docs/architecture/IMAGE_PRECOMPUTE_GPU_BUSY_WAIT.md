# Image execution: bounded pre-compute GPU contention wait

2026-10-25 UTC. Part of the existing GPU-preferred embedding goal, not image-quality
development or a new scheduler.

The physical coexistence test showed that an image unit correctly refuses a busy
shared GPU, but the current image CLI immediately propagates that refusal. Normal
Catalog image materialization calls that same adapter without a resource-wait
boundary. An embedding allocation can therefore cause an otherwise valid image
request to fail before inference.

1. Responsibility: the existing image-provider infrastructure context waits only
   for the shared kernel mutex before model execution. Orchestrator, Catalog and
   the fixed root guardian retain their existing ownership and persistence roles.
2. Canonical source: the unchanged validated image request, selected binding,
   staged inputs and original unit/invocation. No caller-supplied authority is added.
3. Identity/pointers: retain the exact request, source pointers, input hashes and
   unit. Acquisition polling creates no new Job, Artifact, Workflow or request key.
4. Protocol: reuse the closed released request and its existing timeout. No wire
   field, schema bytes, model identity, device permission or output meaning changes.
5. Access/data structures: one nonblocking kernel claim at a time, O(1) state and
   space, at most one poll per second within the declared budget. No queue/cache,
   persistent registry, DB migration or worker-to-worker messages.
6. Concurrency: the unchanged retained-lease context still requires the actual
   root ACK before any model code. The guardian already observes a live unleased
   unit until the existing template deadline; do not extend that deadline.
7. Retry: only `SharedGpuLeaseError(BUSY)` before entering the context may wait.
   INVALID, uncertain ACK/retention, input/hash/permission failure, body failure
   and close failure propagate immediately. Never rerun model work.
8. Compatibility: zero busy-wait budget keeps existing fail-fast behavior. Legacy
   arbitrary-path locks and experimental/trainer policies remain unchanged. Only
   production image CLI calls select the validated request's existing time budget.
9. Dependencies: use existing stdlib time and the existing optional shared-lease
   package. No new dependency, public application endpoint or framework.
10. Verification: real temporary-inode contention/release, bounded timeout,
    invalid/missing inode, post-entry errors and legacy compatibility; then an
    actual normalized V6 image unit waiting for a real existing INDEX allocation
    and continuing under the same invocation. Preserve all earlier failed evidence.
11. Deployment/rollback: change only the standalone image-provider wheel using
    its existing isolated release process with image units quiescent. Preserve
    INDEX/QUERY, numerical CPU/CUDA prefixes and controller pins. Verify wheel
    contents/RECORD and retain the previous wheel for a quiescent rollback.

Failing immediately is simpler but does not preserve usable image generation
during background embedding. Retrying whole requests or changing hardware guards
would create duplicate work or weaken ownership. Bounded pre-entry waiting is the
smallest change at the boundary that already owns this resource operation.
