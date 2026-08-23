# ADR 0036: HWPX Node 22 runtime

## Status

Accepted.

## Decision

The isolated HWPX builder pins Node.js 22.23.2 and Kordoc 4.9.0. Node is installed as the explicitly
qualified Conda package `conda-forge::nodejs=22.23.2`; the remaining environment retains its existing
channels and ownership. The Python document parsers are independently pinned in the reviewed pip
lock. Kordoc optional OCR, PDF, browser, model, and native image dependencies remain omitted.

## Boundary and access pattern

The builder performs a fixed local lookup of one Node executable and one immutable npm runtime, then
executes one offline conversion in a private workspace. There is no dynamic dependency lookup,
network fetch, caller-selected module, or shared cache during a build. Runtime identity remains the
`eom-hwpx` service user; validated artifacts cross to the Manager only through the existing typed
handoff.

## Rationale

Node 20 is end-of-life. The configured defaults channel has no Node 22 package, while conda-forge
publishes the qualified 22.23.2 build. An official archive installed outside Conda would violate the
explicit-environment contract and introduce a second package ownership path. Moving all environment
packages to conda-forge would be broader than necessary, so only Node uses a channel-qualified spec.

## Compatibility and failure behavior

The bridge and Manager capability checks require major version 22 exactly and fail closed on any
other major. The runtime layout verifier pins Node 22's shared-library ABI. Release qualification
must prove Kordoc capability, real offline conversion, package validation, and native structure
counts before installation. Existing Artifact revisions and HWPX bytes are immutable and are not
reinterpreted. Deployment stops the application runner during the environment mutation and rolls
back to the prior Conda revision if verification fails; no build is automatically submitted.
