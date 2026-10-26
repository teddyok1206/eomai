# GPU control failure diagnostics

2026-10-25 UTC. This is a repair within the GPU-preferred embedding goal, not a
new execution protocol or a permission to retry unknown work.

The original INDEX invocation stopped at21:48:09 before a new GPU batch was
bound. Its owner reported `EMBEDDING_BENCHMARK_PEER_INVALID`; a real local Unix
socket reproducer shows that a credential-bearing EOF currently produces this
misleading error. The root unit intentionally discards stdout/stderr and its
entry catches exceptions without a diagnostic, initially hiding the earlier root
failure. Subsequent exact-file forensics identified a performance profiler's
build-id hardlink cache on the host dynamic loader. Removing only that derived
cache restored the original single-link invariant without changing canonical
bytes, permissions or a qualified numerical prefix. Do not infer BUSY or
nonexecution from the channel error alone.

- The existing framing adapter owns EOF classification. An empty stream read
  must produce the already-defined CHANNEL_EOF failure, after closing any received
  unexpected descriptors. Nonempty frames retain exact peer/sender checks.
- The fixed root entry owns optional technical failure reporting. Emit only a
  bounded event, exception class, checked internal code and internal module/line
  sites to the local journal using a nonblocking Unix datagram. Never emit the
  exception message, locals, requests, source data, credentials or a full stack.
- This diagnostic is not canonical evidence, an allocation receipt, source
  authority or a reason to select CPU. Logging failure must preserve EXIT1.
- No schema bytes, worker messages, DB fields, queue, dependency or numerical
  runtime change. Access is one bounded datagram and O(1) bounded traceback work.
- Test real Unix EOF, nonempty sender rejection and descriptor cleanup, plus
  diagnostic redaction/size and transport failures. Root/source-owner successors
  require the existing compatible release and quiescence procedure; never edit a
  qualified numerical prefix or an immutable installed release in place.
- Preserve original failed units/receipts. Reconcile an unbound original through
  the supported application only after exact root/numerical process/FD evidence;
  do not manually UPDATE rows, replay an old unit, or call it a success.
- Operational profiling must use `perf record --no-buildid-cache`: the default
  cache can create hardlinks to protected host libraries. A supposedly read-only
  diagnostic must not alter installation invariants. Do not weaken the existing
  single-link rule to accommodate a debug cache.

## Minimal candidate selection and original-plan fence

The root diagnostic can be selected independently from the metadata owner: its
channel/schema bytes and the qualified numerical entry are unchanged. Prefer
the existing typed `controller_release` selection and matching protected root
environment over creating another INDEX Identity/grant revision. Keep metadata
SDK07, source policy, original pending Workflows and CPU QUERY unchanged. The
metadata-side EOF classification remains staged until its next compatible
metadata release; do not describe that classification as already active.

Prepare and hash the two exact before/after files and retain rollback bytes.
Request the existing main-only SIGTERM drain, which sets the service's Event
without marking the unit deactivating or killing a numerical child. Select both
files only after natural EXIT0 and the existing physical process/retained-FD
quiescence observer passes; then restart the same metadata source/Identity.
Configuration mismatch leaves that service stopped for inspection, not partially
activated. No DB write, new protocol, source query or model run is part of this
selection. The larger full metadata/Identity successor is unnecessary for this
controller-only diagnostic change.

**A controller commit is part of the deterministic DOCUMENT parent identity.**
Do not promote even this small candidate while an earlier original allocation
remains unbound/CLAIMED. It would accidentally bypass the original recovery
boundary. The23:33 deployment continuation was therefore stopped **before**
selection. INDEX drained naturally with EXIT0, and the exact existing SDK07 /
controller04 configuration was restarted; no original source request was re-keyed.
The prepared before/after files are candidates, not an operating release.

First reconcile original `job_04e9e09afc994736ae063b882e4bb854` through the
existing official planning failure operation using independently checked actual
root/unit/input evidence. Never fabricate a numerical retirement for an instance
without that receipt. Descriptor metadata alone does not prove numerical start:
the original protected `10-allocation.conf` does exist, while its native unit has
no recorded invocation and the original input/output files remain empty. Keep
the failed root and no-grant facts distinct. Candidate SELECT additionally reads
the exact original through the official Orchestrator metadata reader and refuses
promotion unless that original has an evidenced FAILED history and no route/BIND.

The original was officially closed at2026-10-26 00:12 UTC using the
[unbound-controller operation](UNBOUND_EMBEDDING_CONTROLLER_FAILURE.md), with
exact replay and a canonical Artifact; its failed root was preserved. At00:32
the explicitly installed successor24555547 was selected through the two-file
controller boundary, leaving metadata SDK07/Identity and numerical SDKeae2c0d3
unchanged. Exact selected-file and unchanged-pin read-back PASS. INDEX restarted
as invocation9718f2ed05ac404e84ce7a69559b110c. Earlier4f1a838a prepared bytes and
cancelled/failed deployment attempts remain history, not active releases.

Historical parents from before the **current service revision's canonical
Identity REGISTER event** are quiescent earlier-revision history, not current
executable claims. Keep them unchanged; current source fences cannot adopt their
old request identities. The gate still checks current-epoch unbound parents and
exact-current-revision GPU Workflows after natural drain, as well as actual
processes/retained FDs. Do not use a global logical-service-ID scan to relabel old
history as current failure or change history merely to satisfy a rollout check.
