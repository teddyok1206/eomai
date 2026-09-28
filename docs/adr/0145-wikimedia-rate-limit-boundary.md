# ADR 0145: Bound Wikimedia rate limits inside reference acquisition

## Status

Accepted — 2026-09-28 UTC.

## Context and responsibility

The image-reference adapter is the only component allowed to dereference the immutable
Wikimedia candidate identities selected for a generated visual. A live item workflow showed that
Commons can return HTTP 429 with `Retry-After` while metadata discovery still succeeds. Mapping
that response to `WORKER_UNAVAILABLE` caused the workflow runner to repeat the complete image
worker, including another model invocation, without respecting the provider delay.

The canonical sources remain the verified Wikimedia page revisions and downloaded original-byte
hashes in the approved visual-reference bundle. The workflow, image step, drawing, intent, bundle,
normalized member and generated image retain separate immutable IDs and hashes. No database,
artifact, schema or pointer shape changes.

## Decision

- Identify the client with a policy-compliant product/version and public contact URL.
- For HTTP 429 only, the acquisition adapter reads a decimal `Retry-After`, accepts values from
  1 through 30 seconds, sleeps serially, and retries at most twice. Missing, malformed or excessive
  delays fail closed as `VISUAL_REFERENCE_SOURCE_UNAVAILABLE`.
- All other network failures keep their stable unavailable code. Redirect, host, DNS-publicness,
  media, license, size and content-hash checks remain unchanged.
- Once the adapter exhausts its bounded provider retries, the workflow runner treats the exact
  `VISUAL_REFERENCE_SOURCE_UNAVAILABLE` precommit detail as terminal. It does not rerun the entire
  image worker up to the generic step-attempt ceiling.

## Access patterns and complexity

The adapter performs ordered iteration over at most five candidates. It uses no persistent cache
or new index. Retry state is two scalar counters per HTTP request: O(candidates) requests, O(1)
additional memory, stable candidate order. Requests remain serial and the systemd unit remains the
outer 240-second execution bound.

## Failure, concurrency and idempotency

Provider reads do not mutate EOM canonical state. A successful acquisition is still committed once
by the orchestrator through the existing intent/bundle/member pointer boundary. Failed attempts
publish only their immutable failure result. Replaying an already committed bundle remains
idempotent; no worker or adapter writes to NAS.

## Alternatives

Retrying the whole image worker is simpler locally but repeats an unrelated model call and can
amplify a provider rate limit. Downloading only the primary candidate would require a successor
bundle contract because version 1.0 binds every intent candidate to an independently hashed source.
The bounded adapter retry is the smallest change that preserves the released contract.
