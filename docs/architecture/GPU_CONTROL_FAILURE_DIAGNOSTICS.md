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
