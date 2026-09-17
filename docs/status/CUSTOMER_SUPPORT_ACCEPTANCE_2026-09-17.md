# Customer Support Live Acceptance

Status date: 2026-09-17 (UTC)

## Verdict

The authenticated Scientific Studio customer-support path is active and passed one bounded live
canary. The canary used the normal Workflow command, slot-06 capacity lease, isolated one-shot
worker, Orchestrator validation, immutable Artifact commit, and owner-scoped API projection. It did
not use a direct Web-to-Codex call, a resident model process, a worker NAS/DB write, or an external
LLM API.

```text
CUSTOMER_SUPPORT_LIVE=PASS
WORKFLOW_TERMINAL=COMPLETED
OWNER_PROJECTION=ANSWERED
IDEMPOTENT_REPLAY=PASS
ACTIVE_COMMANDS_AFTER=0
ACTIVE_JOBS_AFTER=0
HELD_LEASES_AFTER=0
MANUAL_STUDIO_REVIEW=PENDING
```

The manual Studio observations remain consolidated in the
[customer-support checklist](CUSTOMER_SUPPORT_MANUAL_CHECKLIST_2026-09-17.md). Automated live
acceptance must not be reinterpreted as a visual-usability PASS.

## Compatible installed set

- live-acceptance code checkpoint: `746252127e281eeaa3aca96dc31367c9fd97c8ad`;
- Application API: `746252127e281eeaa3aca96dc31367c9fd97c8ad`;
- Scientific Studio Web: compatible customer-support release
  `d49e12061de52aad0ea92e62d08b0037392820f3`;
- dedicated support worker template introduced by
  `5d87b3f5b2de66c1dc5e02bc0de6333cda0f67f5`;
- installed support-unit SHA-256:
  `1c8672c001c0670b405dba697e7d6e91ea89e97a783ef98c8f4829a81d553ce2`;
- migrations through `20260917_0037`;
- Workflow `customer-support@1.0.0`, role `workflow-role/1.22.0`, result
  `customer-support-result@1.0`, and plan `resolved-execution-plan/10.0`;
- `gpt-5.6-terra/medium`, slot 06, read-only sandbox, network disabled, 900-second fixed ceiling.

Later documentation-only commits do not change this installed runtime identity.

The existing slot-06 analysis template retains its independent 7,200-second ceiling. The support
template does not add capacity: both templates use the same slot-06 account and atomic capacity
lease. Recovery observes both exact instance identities and fails closed on ambiguous history.

## Live receipt

The successful canary identities are recorded without its question or answer content:

- Workflow: `workflow_e8c31a331dca4fbf91cef426fcff5c47`;
- START command: `wfcmd_d671801b6a1a48d4971f24b9d5347234`;
- Job: `job_9a93c7cdf39e4636b55ef355e99d9125`;
- Artifact: `artifact_f4fdc24515ed4cefa56bc41799585101`;
- Artifact Revision: `rev_78702e73736048efb6cf36e9aabfc9cb`;
- result content SHA-256:
  `sha256:92038ea0e236be355475b6c6aab1d5b8a16572523c8f9079ecf6248a4d9c0f59`.

The Job exited successfully, the support systemd instance reached `Result=success`, exactly one
approved result Artifact Revision was committed, and the result binding matched the Workflow, Job,
Artifact, revision, schema, lifecycle, and content hash. The canary reporter emitted no answer
content. Replaying the exact authenticated idempotency key and request returned the same Workflow
and command and did not launch another worker.

## Failures preserved during rollout

Two rollout findings remain immutable evidence rather than rewritten history:

1. The first support attempt was rejected before worker launch because the generic slot-06 unit had
   a fixed 7,200-second ceiling while the support plan required exactly 900 seconds. The protocol-
   safe correction added a dedicated root-owned support template instead of weakening either
   ceiling or changing the failed Workflow.
2. The successful worker result initially produced an owner-projection HTTP 500 because the query
   adapter expected the obsolete artifact/task type `workflow_diagnose`; the Orchestrator correctly
   committed the canonical `workflow_support` type. Commit `7462521` aligned the projection and
   added a negative regression for the obsolete type. Exact idempotent replay then returned
   `ANSWERED` without a second model execution.

No database row was directly edited, no failed state was reinterpreted as success, no lease was
forced, and no new idempotency key was used to hide an uncertain outcome.

## Verification summary

- customer-support and worker/systemd focused suites: 100 + 23 PASS;
- API-environment non-image unit suite: 2,186 PASS;
- image-specific environment suite: 16 PASS;
- deployment/runtime-isolation suite: 63 PASS;
- final owner-projection regression: 12 PASS;
- Ruff format/check: 1,367 files PASS;
- strict mypy on the changed source: PASS;
- root-owned worker template, readiness contract, authorization positive/negative probes: PASS;
- post-canary API readiness and service activity: PASS;
- post-canary active Workflow commands, Jobs, API idempotency records, and held leases: all zero.

This evidence approves the current bounded feature. It does not approve attachments, arbitrary
resource pointers, automatic retries, mutation-capable support workers, emergency access during a
total Web/API/login outage, or operator impersonation.
