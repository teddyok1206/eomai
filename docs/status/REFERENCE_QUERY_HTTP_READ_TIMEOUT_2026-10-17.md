# Original HTTP QUERY: READY, result delivery still unavailable

Observed2026-10-17 UTC. This is not full goal/consumer acceptance. The sections
below preserve successive observations, not claims that all older PIDs/sessions
are still current. Latest7fcd0865 deployment/restoration and fresh original-request
verification are in the [operating record](../operations/SHARED_PROVENANCE_READ_RELEASE_2026-10-17.md).

The original continuation process remains alive; no replacement login, request,
Workflow or idempotency key was created. Its fixed metadata log records:

-14:08:26: existing `guiadmin` login PASS, no persisted credentials.
-14:08:40: original Workflow `workflow_a0833f96b5154c3da4c5e5961eb9a209`
  preparation reply READY, error null.
-14:09:20: first similarity-context HTTP read returned503,
  `SIMILARITY_CONTEXT_UNAVAILABLE`; observation stopped without automatic retry.
-API metadata for request `req_f79f480fc81e37f177cded94cbe871b5` shows
  `POST /knowledge/inference-transfer/similarity-context`, duration30018.781ms.
  The two preceding preparation calls took13991.0ms and9543.346ms.
-The current API source client's Catalog socket deadline is30.0s. The timing is
  evidence of reaching that delivery deadline, not yet proof of the underlying
  server bottleneck, process state or current installed-source equivalence.
-A single explicitly requested same-key observation on the same live Python
  process at14:37:53 returned403, `AUTH_REAUTHENTICATION_REQUIRED`, then stopped
  without automatic retry. This proves fresh authentication is now required;
  it does not distinguish access-token expiry from another freshness boundary.
  The code was recovered by parsing the existing validator log's JSON event after
  its control-prompt prefix, without reading terminal history or credentials.

The process state is AWAIT_EXPLICIT_REPLAY, not LOGIN. The previous LOGIN reports
were accurate at their earlier14:05 observation but are not current. The original
session is retained only in memory; no credential/buffer/memory extraction,
fresh request key, model retry, root/admin impersonation or TTL change occurred.
Only whitelisted metadata was read from the validator's existing log. A temporary
future-output-only event pipe was detached; terminal history was not captured.

## Next action within the unchanged goal

Prioritize the actual context delivery boundary: compare installed API/Catalog
source and pinned request; measure scope capture, exact source/profile/index reads,
query/result decoding and final authorization in the supported owner. Check
repeated parse/hash, N+1, redundant whole-population materialization and actual
query plans before changing code. Preserve all current permissions, source/report/
Graph/policy/index pins and exact original query/result. Do not increase deadlines
as a substitute for diagnosis, omit source validation, substitute latest, or
regenerate the original QUERY. Reuse the same original request for final live
verification when a valid supported operator session is available.

This does not reopen completed corpus/HWPX work or change the scope. It prioritizes
an observed delivery failure over activating further consumers. Private native
admission/tool delivery and CPU/CUDA comparison remain required and incomplete.

## Installed4222ca9a follow-up, actual same-session evidence

The original old observer was stopped through its supported QUIT after its
actual403; its history remains. Replacement PID496875 authenticated successfully
at16:11:33, with credentials only in memory, and read the SAME original Workflow/
request/key as READY at16:11:45. Context still returned503 at16:12:26;
API request `req_58728b6b35eb653c14f909b7cee33dbd` lasted30,441.107ms.
Thus the installed root/raw/frozen Item/report reuse is not live delivery PASS.

One explicit same-memory-session replay for resource diagnosis read READY again
at16:22:03; context `req_994f3f65711e41407a0b4f43f3623f7f` returned503 at16:22:43,
30,037.944ms. No new key, QUERY computation, model or automatic retry. The same
process remains at its supported AWAIT_EXPLICIT_REPLAY prompt, not LOGIN.

An actual65-second pidstat observer (PID748885, normal terminal completion) read
kernel process-resource metadata only, not process memory/credentials/stacks.
The40 samples16:22:04–43 showed mean52.15%/max97% Catalog CPU, max838,984KiB RSS
and zero sampled block-read kB/s. These aggregate counters do not prove there
was no NAS access or identify an individual function. The observation includes
the preceding preparation replay; it is not isolated context-only CPU timing.

Read-only metadata inventory found521 accepted V10 reports totaling6,462,310 raw
bytes, max17,314: no evidence of a32MiB **report** model-charge overflow. These
521 are not a new backfill denominator or full current Item/model-cache size.
A separate read-only521-row request/result/receipt metadata profile measured
7,354ms with cProfile overhead (5,860ms JSON Schema,1,494ms typed-model stages).
It read no NAS/source bodies, mutated no DB rows, and establishes neither whole
request latency nor current-user/source authority. Other-role pg_stat_activity
fields were redacted by PostgreSQL; null is UNKNOWN, not proof of no wait.

Source inspection found another repeated immutable decoding path: shared legacy
batch/acceptance/extraction/layout models are reconstructed in each fresh
population cache, and the intervening Artifact wrapper loses the optional model
port. Extend the same root model cache instead of inventing another cache or
omitting full-scope validation. [Scoped follow-up design](../architecture/SCOPED_TYPED_ARTIFACT_DECODING.md#shared-past-exam-provenance-follow-up--design-before-implementation).
This is a concrete repeat-work correction to test, not yet a proven complete
explanation/fix of the actual deadline. Keep30s unchanged until further evidence.

## Installed7fcd0865 original read still fails

The [actual compatible release](../operations/SHARED_PROVENANCE_READ_RELEASE_2026-10-17.md)
completed normal owner drain, installation, restoration and startup/health checks.
The previous session actually expired401 and was terminated through QUIT.
One failed fresh login remains recorded. At17:09:09 a new official login passed,
and the unchanged original request/Workflow was READY17:09:21. Its context read
returned503 `SIMILARITY_CONTEXT_UNAVAILABLE`17:10:01. No new key, numerical model
execution, authority/TTL expansion or deadline increase was used. The live
observer retains its same memory session at AWAIT_EXPLICIT_REPLAY; do not replace
it simply because a read timed out. Shared decode source speedup is not sufficient
evidence that the actual delivery bottleneck has been removed.

## Installed timing diagnostics; preparation fresh-auth gate

df408fef adds only bounded stage-duration metadata and passed actual compatible
installation/restoration/health. The same live observer's explicit17:31:32 replay
received403 `AUTH_REAUTHENTICATION_REQUIRED` from preparation, before context.
The new release is **not measured** by that denial: last real context503 is still
7fcd0865 at17:10:01. The existing read-only completed-context route is separate
from fresh-auth `WORKFLOW_START` preparation. Preserve both permission boundaries;
fix the future diagnostic sequence rather than reducing auth freshness or
claiming all reads require a new login. The user requested no interactive login
while asleep. [Exact operating evidence and safe next actions](../operations/SIMILARITY_READ_STAGE_DIAGNOSTICS_2026-10-17.md).
