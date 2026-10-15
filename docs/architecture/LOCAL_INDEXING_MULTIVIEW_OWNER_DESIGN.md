# Bounded multiview composition of the existing INDEX owner

2026-10-15 UTC. Required continuation of the original incremental-embedding goal.
This design does not activate a new service, source grant or model execution.

1. Responsibility: the installed INDEX owner composes up to three existing
   namespace-specific owner/executor/Runner/reconciler instances. Catalog retains
   eligibility, binding/index publication; Identity retains current service trust.
2. Canonical source: current committed Graph membership, accepted reports and the
   existing per-namespace registry. No copied target list, new queue or tracker.
3. Identity: logical index/revision and encoding/binding identities remain unchanged.
   Namespace includes view, space, recipe and projection pins; never mix views.
4. Pointers: each leaf receives one exact namespace and the unchanged shared
   model/runtime/policy/source configuration. Existing source/hash/current-authority
   fences run for every leaf. Configuration is selection, not a source grant.
5. Access patterns: existing actor/family-filtered ordered queue peek, further
   narrowed by exact immutable initial-request namespace; independent per-namespace
   missing-binding discovery. No corpus scan in scheduler code.
6. Structures: immutable tuple of at most three leaf runtimes and fixed-size
   deadline/signature arrays, round-robin cursor. No process-global mutable state.
7. Cost: O(V) idle observations per poll, V<=3, O(V) scheduler state. Queue uses
   existing actor/state/time indexes then the bounded namespace predicate; this
   does not claim a new namespace index. Measure actual query plans before adding
   one. Numerical admission remains globally serialized by the existing launcher.
8. Concurrency: each leaf uses the existing exact candidate claim/lease/START
   transaction. Queue selection is not authority. Claim still reparses the pinned
   request and validates the actual namespace-specific owner/executor. On process
   restart each leaf resumes its own existing queue before discovering more work.
9. Dependencies: schema/value models below application composition; scheduler
   handles only typed leaf runtimes. No worker IO, DB/NAS ownership or ML imports
   move into domain/contracts. Existing controller engine/publisher/fence are shared.
10. Failure/retry: one leaf failure stops the owner as before; do not mark other
    views successful or substitute a different namespace. SIGTERM drains the
    current command, then performs no further claim or discovery. Deadlines are
    per leaf, so a busy view cannot starve the other views. No automatic new-key
    retry or failed-history rewriting.
11. Simpler alternative: three independent services would duplicate fixed unit,
    identity and deployment boundaries; an unrestricted shared actor-only Runner
    could select a command for the wrong namespace. Extend the existing owner with
    a bounded tuple and namespace selection instead of another scheduler framework.

Protocol first: preserve configuration1.0 bytes and parsing. Add closed JSON
Schema2020-12 configuration2.0 with its existing primary `namespace` plus one or
two `additional_namespaces`. Shared frozen values are inherited, not duplicated
as whole configurations per view. All namespaces use the same space/recipe and
projection version, with distinct views. Old one-view deployments remain1.0.
Additional namespaces never manufacture source permission: explicit current
Catalog grant/runtime/identity successors must authorize them before installation.

The shared selection also requires the same storage partition and population
scope. A different view is not permission to quietly change the selected corpus.

Required checks: both wire versions/canonical bytes/closed fields/copied model
revalidation; duplicate or mismatched namespace rejection; exact SQL namespace
selection and existing actual owner claim guards; round-robin progress despite a
busy leaf, independent deadlines, per-view journal dedup and stop during command
or discovery. Use disposable PostgreSQL for any mutating queue acceptance, not
production. Source, installed, activated and actual all-view coverage stay separate.

## Source checkpoint

Both closed configuration versions now parse with schema-first validation and
canonical round-trip. The1.0 schema raw hash and existing family inventories are
unchanged. One shared set of frozen model/recipe/runtime/database/verifier pins
supports up to three namespace leaves; no complete configuration is copied per
view. Before serving, every leaf resolves its own existing source controls under
the actual shared service fence. If any leaf fails, construction disposes the
engine and no queue processing starts.

The existing queue selection value accepts an optional exact namespace **only for
service-owned INDEX**. SQL selects that namespace from immutable initial-request
JSONB in addition to the existing family/actor and ordered LIMIT1. Actual claim
still reparses the original request and invokes the namespace-specific owner;
selection itself grants nothing. Human QUERY and ordinary role routing retain
their original paths. Three leaf instances share one engine/publisher/authority/
launcher and are invoked sequentially with per-view deadlines and journal dedup.

Source regression333 PASS/52.61s includes closed inputs, old configurations,
copy/coercion rejection, all three leaf compositions, busy-primary fairness,
independent deadlines, stop during command, native INDEX/QUERY/ordinary routing,
source/runtime fences and dependency/release inventory. The69-case focused gate
overlaps those333; do not sum them. Strict mypy4 production modules, Ruff/format
and whitespace checks PASS. Actual operating CPU/native launch count has not
changed because of this source work.

The first actual PostgreSQL stage gate126 PASS/96.37s verified namespace inclusion
and exclusion at one exact Workflow. Adding an EXPLAIN/one-statement check exposed
a fixture assertion against the global FIFO: retained synthetic cohorts reuse one
service ID, so the globally oldest valid command belongs to an earlier cohort.
That failure remains recorded (125 PASS/1 failure); no production rule or retained
row was changed. The corrected test pins its own immutable Workflow for isolation,
retains all old evidence, and inspects both actual SQL statements/plans. The final
guarded stage rerun **126 PASS/94.02s** verifies one SQL statement per selected
namespace, actual JSONB inclusion/exclusion, LIMIT plans, unchanged pending state
and no model execution. This is a Workflow-scoped test-plan observation, not a
production global-FIFO throughput benchmark. The disposable DB postcheck confirms
the expected marker/owner, migration0055 and zero other connections. No actual
service authority is inferred from its explicitly synthetic IAM/source fixtures.

Retained private logs in the current development window:
`multiview-owner-{source-final,shared-regression-final,source-types-final}.log`,
`multiview-owner-disposable-stage-{first,final,reviewed}.log`. The middle DB log is
the failed fixture experiment; it is not overwritten by the reviewed PASS.

Activation remains separate: selected ownerae8f8bf6 is inactive after the actual
four-target delta, current operating CONTENT_ONLY coverage6/520. This source
neither activates configuration2.0 nor authorizes extra namespaces, and does not
replace the held HTTP canary or the inactive83bad API/provider candidate. Select
an explicitly reviewed INDEX-owner successor and compatible current grant/identity
before activation; never silently pick latest or patch the old prefix.

## Packaged and installed inactive candidate

Reviewed INDEX candidate`d4846220f1afbebaa8bb79507297eed42cea9219` passed the official
API build-only/RECORD/source inventory/installed simulation. Its dist directory is
`/tmp/eom-api-build/d4846220f1afbebaa8bb79507297eed42cea9219.uaPiGK/dist`.

| Wheel | Raw SHA-256 |
| --- | --- |
| Platform | `5a8e74bfefee586845b04d6f09ba7444482d776267f092ef998651d48ad492f3` |
| API contracts | `3fcbca8d71eb49f06faf0fe3ef30c549f96d5770372f2857e98d3b06e02177b1` |
| API (built, not installed) | `d167e5f0138bf056429d9a26bf880f1cbbc688a65ddd823765177812905597b9` |

Independent isolated two-wheel import/source proof28 plus7 changed INDEX members
PASS. The latter also round-trips both configurations from a content-free synthetic
selection, imports the actual scheduler/factory and checks exact per-view selection.
Checkout imports, old installed EOM fallback, API-wheel fallback and numerical ML
imports are denied; no DB/login/model/service operation is performed by this proof.
These are member/import checks, not additional pytest cases.

At23:13 UTC the existing root-protected no-clobber installer published this exact
owner pair under`/opt/eom/embedding-owner-releases/d4846220f1afbebaa8bb79507297eed42cea9219`.
Root ownership, directory0755, retained wheel hashes and terminal installer result
were checked. **OWNER_ACTIVATION=NOT_PERFORMED; CPU_RUNTIME=UNCHANGED**. The active
API/platform2857bf77, native QUERY owner8c411041, old INDEX selectionae8f8bf6,
identity revision11, data/native policies, configuration and migration0055 remain.
The separate reviewed83bad API/provider staging is not silently replaced by this
INDEX-only candidate. Future documentation commits do not change these pins.

The first direct installer invocation failed before entry because the protected
script is intentionally0444, not executable. Its log is retained; the supported
explicit`sudo -n /bin/bash <protected installer>` invocation then succeeded without
changing file permissions, credential TTLs or the user authentication process.
Logs:`multiview-owner-release-build.log`, `multiview-owner-pair-closure.log`,
`multiview-owner-inactive-install.log`(failed invocation) and
`multiview-owner-inactive-install-reviewed.log`(successful inactive install).
