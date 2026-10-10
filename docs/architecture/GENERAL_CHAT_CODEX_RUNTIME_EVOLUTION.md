# General Chat Codex runtime evolution

Status: implementation design approved by the operator on 2026-10-10 UTC.
Runtime acceptance is separate from this source document.

## Boundary and canonical source

The six fixed-worker compatibility use case does not prove the dedicated General
Chat app-server path. Updating the shared Codex installation therefore requires
two independent checks before restoring normal producers: the existing bounded
worker matrix and an authenticated chat application canary, including supported
RAG tool use. No external LLM API, credential transfer or model-default change is
introduced. The existing root-owned `general-chat-model.env` remains the selected
configuration source; CLI/npm files are installed executable materialization, not
database identity. Existing chat history and canonical Artifact receipts remain
immutable.

## Additive contracts and identity

Preserve every released worker-policy and dispatch V1–V4 schema byte. Add only
worker-policy V5 and dispatch V5. Policy V5 uses the version-neutral native adapter
profile `codex-app-server/environment-free/2.0` and a frozen `native_runtime` value:
`cli_version`, `cli_launcher_sha256`, and `cli_binary_sha256`. These values are
explicit operator selections captured while chat services are stopped, never
worker-supplied authority or automatic adoption of the current installation.
They travel as three nonsecret keys in the existing protected model environment.
All keys must be present together. Selected runtime V5 requires the already
configured protocol-4/RAG policy; it must not activate RAG on a legacy protocol-3
configuration.

A single public policy-to-transport mapping maps policy V5 to existing RPC/turn
capability V4. Request, reply, owner, tool, turn and result families remain unchanged.
Dispatch V5 embeds exactly policy V5 and retains the exact ticket/input pointer.
Historical RESULT lookup continues using its historical ticket and policy hash,
not the currently selected policy. Published result, input and dispatch schemas,
members, revisions, lifecycle, media type, permission and hashes remain checked.

## Structures, cost and dependency direction

Dominant operations are immutable key lookup, bounded feature membership, ordered
RPC events, and append-only turn history. Use frozen typed values, a fixed mapping
for policy families, and existing indexed repositories/artifact pointers. No new
DB table, queue, search index, cache, framework or binary database payload is needed.
Scale remains one resident dedicated chat process and bounded transport events.

Extract protected CLI file identity/hash checks into one infrastructure adapter
used by both compatibility maintenance and native chat. Hash launcher/native bytes
once per startup epoch; check inode/size/timestamps/permissions and selected
symlink target in O(1) before launches and subsequent chat admission. File hashing
is O(executable bytes), metadata storage is O(1). Domain/protocol value objects
must not import subprocess/filesystem infrastructure. Existing CLI, systemd,
configuration, auth, Artifact and database adapters retain their responsibilities.

## Admission, installation and rollback

Root explicitly pins the selected installed CLI while both chat services are
stopped. Startup validates root ownership, protected ancestors, single-link
regular files, exact version and hashes within one file epoch, existing disabled
feature inventory, strict configuration and the native app-server initialization
and text/RAG-only tool boundary. Unknown/incompatible behavior is NOT_READY; no
provider, credential, version or tool fallback is allowed. Same-version binary
replacement also invalidates admission.

Before npm replacement: record the selected package/version/hash and protected
policy/config predecessors; preserve an exact manifest-backed recoverable package
and symlink; confirm queue/lease/native-process quiescence; stop producers. The
compatibility verification wrapper is not itself permission to replace a live
CLI. Install the explicitly selected stable npm version with the reviewed layout;
keep producers stopped across package replacement and verification. After a new
canonical bounded worker PASS receipt, install the existing V3 admission policy,
refresh supported OBSERVE snapshots, and perform the separate authenticated chat
canary before declaring the whole update complete.

No new identity is submitted to evade an unknown started execution. First probe
failure stops the remaining matrix. Timeout means inspect the same turn/run and
local checkpoints, not resubmit. Restore exact prior runtime/policy/config only
after physical worker quiescence; preserve failed receipts and histories. Future
versions with the same supported behavior require new explicit runtime pins and
the same checks, not a source-level version-number edit. Actual protocol/tool
changes still require a reviewed adapter/contract successor.

## Simpler alternative and tests

Changing `EXPECTED_VERSION`, accepting a version range, or rewriting a released
native-profile const cannot preserve truthful immutable provenance and does not
detect changed executable bytes. A new queue or a parallel chat implementation
would duplicate an existing boundary. The narrow successor and existing deployment
configuration are sufficient.

Required tests: predecessor schema bytes; V5 schema/Pydantic parity; exact public
mapping; all-or-none protected pins; legacy serialization; wrong version/hash,
changed files/symlink/ancestors; guard epoch and O(1) subsequent checks; unchanged
strict disabled features; old-policy lookup/recovery; dispatch V5 publication and
resolution; pointer/hash/idempotency/concurrency/dependency boundaries; installer
exact-predecessor update/replay; authenticated new-version text and RAG canaries.
Mutating PostgreSQL tests use the existing guarded disposable database only.
