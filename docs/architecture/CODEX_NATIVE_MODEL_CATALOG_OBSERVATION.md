# Native Codex model catalog observation

The existing Orchestrator `OBSERVE` command is the sole owner of this read-only
observation. The fixed-slot worker asks its own authenticated Codex App Server
for `account/read`, `account/rateLimits/read`, and `model/list`; it never starts a
thread or turn. No new queue, DB table, inference call, external LLM API, or
credential copy is introduced.

Canonical evidence is one immutable, sanitized command-result document, keyed
by command ID and exact binding/slot. The additive usage observation `1.1` and
command result `1.2` preserve earlier schema bytes. The catalog's content hash,
CLI version, UTC observation time and bounded expiry identify the native
snapshot; auth-binding freshness is not catalog freshness. Raw account details,
provider descriptions, credentials and arbitrary provider fields are discarded.

Access patterns are ordered pagination and unique model/effort lookup. A bounded
tuple preserves a deterministic model-ID order; sets detect duplicate IDs,
efforts and cursor cycles in O(n) time/space. At most 64 models and four pages
are accepted. Small metadata stays in the existing control result JSON field;
there are no binary payloads or new indexes.

The existing command claim fences the slot while observation runs; the existing
transaction rechecks the binding resource version before committing the result.
Workers only write an exclusive local `/run` handoff. Orchestrator reads it using
the existing same-descriptor, ownership/mode/size/hash checks. A command replay
reuses its immutable terminal result and does not create another catalog record.

App Server IO, pages, model counts, strings, cursors, elapsed time and serialized
catalog size are bounded. Incomplete, oversized or invalid catalog results are
explicit `UNAVAILABLE` observations with no partial models. They do not turn a
successful usage observation into a false auth failure. Missing native metadata
must not silently be replaced with the reviewed policy or a hard-coded model
list. Historical V1 usage handoffs remain readable during a coordinated rollout.

`OBSERVED` means only that `model/list` supplied that metadata. It does not mean
operator admission, structured-output support, educational quality or a passed
preset evaluation. Reviewed capability snapshots remain separate and unchanged.
Provider efforts such as `max`/`ultra` may be recorded as metadata but remain
outside EOM's execution-candidate enum. UI selection must intersect native
catalog support, reviewed policy and role/slot eligibility, and must not activate
a new production preset merely because catalog observation succeeded.

Contracts/domain remain free of subprocess/storage code. The existing worker
observer and Orchestrator adapters own IO; API/Web only project validated
metadata. The simpler alternative of filling dropdowns from policy YAML is
insufficient: it does not observe what the authenticated native CLI advertises.
