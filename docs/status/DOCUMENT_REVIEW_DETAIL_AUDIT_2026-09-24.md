# Document Review Detail Audit — 2026-09-24

## Purpose and scope

This is a read-only audit of whether the educational document-review feature performs and records
detailed review work. It distinguishes three claims:

1. what the worker instructions ask the reviewer to do;
2. what JSON Schema 2020-12, Pydantic, and application validation actually enforce;
3. what one recent completed paired review actually recorded.

No source document, Workflow, Job, result, annotation, database row, or NAS artifact was changed.
The document records only content-free counts, states, contract identities, and limitations. It does
not reproduce Item text, findings, worker prompts, or results.

## Reviewed boundaries

- Workflow: `pdf-document-review@1.1.0`.
- Role protocol: `workflow-role/1.26.0`.
- Result: `pdf-document-review-result@2.0`.
- Current reviewed control candidate: `pdf-document-review-control-bootstrap/4.0` using
  `gpt-5.6-terra` with `xhigh` reasoning in slot 06.
- Presets: immutable `PROBLEM_SET`, `WEEKLY_WORKBOOK`, and `MOCK_EXAM` snapshots.
- Annotation derivative: `document-review-pdf-annotation/2.0`, Catalog `catalog/1.21`, profile
  `NUMBERED_BOXES_WITH_NATIVE_COMMENTS`.

The inspected live evidence is the completed paired Workflow
`workflow_8b74ce941c8447bdad43429a1269e3b1` and its V2 annotation
`docannotation_926ed12d898be261f1657cae02fd4772`. These identities are audit references, not
browser inputs or mutable aliases.

## What is strong today

### Review instructions

The role instruction requires the reviewer to:

- read the question and solution documents from beginning to end;
- solve each Item independently before comparing the supplied answer and explanation;
- check scientific accuracy, answer uniqueness, sufficiency of conditions, and explanation logic;
- inspect tables, figures, equations, values, units, axes, legends, symbols, terminology, numbering,
  print readiness, difficulty flow, duplication, and curriculum scope;
- create verification targets before the verdict, re-check candidate issues, and classify each as
  `CONFIRMED`, `DEMOTED`, or `UNCERTAIN`;
- turn only confirmed candidates into findings;
- bind every location to a role, page, page-image SHA-256, parts-per-million rectangle, and optional
  quote hash;
- represent each question-to-solution comparison as a typed cross-document check without inventing
  a missing solution location.

The preset criteria add product-specific detail for N제, 주간지, and 모의고사. User guidance is
normalized, bounded, hashed, and additive; it cannot replace the fixed safety or result contract.

### Contract and application validation

The released contract and application boundary verify:

- exact source document and revision identities, source PDF hashes, preset revision/hash, request
  hash, and guidance hash;
- role-correct page identities and exact page-image hashes for every emitted anchor;
- bounded in-page rectangles, quote hashes, sorted unique target/candidate/check/anchor identities,
  and contiguous finding ordinals;
- exact equality between each confirmed candidate and its emitted finding;
- operation-specific recommendation payloads (`REPLACE`, `INSERT`, `DELETE`, `MOVE`, `REDRAW`,
  `VERIFY`, `NONE`);
- exact Job, Workflow, step, attempt, Artifact, Artifact Revision, manifest, event, schema, lifecycle,
  byte count, and content-hash bindings before the result is exposed or annotated;
- `mutation_performed=false`; workers cannot edit the source or write NAS.

The native-comment annotation successor resolves that exact committed result. It creates one panel
entry per finding and document role while retaining every red location box, verifies standard PDF
annotation dictionaries and forbids external actions, embedded files, JavaScript, launch actions,
and remote destinations before committing a derived Artifact.

## Recent live-result evidence

| Check | Observed result |
| --- | --- |
| Source roles | `QUESTION`, `SOLUTION` |
| Source pages | 14 question + 7 solution = 21 |
| Verification targets | 8 |
| Verification axes | scientific accuracy, answer uniqueness, solution consistency, curriculum scope, originality, visual content, document structure, assessment balance |
| Verification states | 6 verified, 1 failed, 1 insufficient |
| Question-to-solution checks | 25 |
| Checks with both role-correct anchor sets | 25 |
| Cross-check states | 25 matched |
| Pages touched by target/cross-check/finding anchors | 21 of 21 |
| Candidate dispositions | 1 confirmed |
| Published findings | 1 low-severity structure finding |
| Recommendation operation | `REDRAW` |
| Source mutation | false |
| V2 native comment entries | 1 in the relevant role PDF |
| Exact replay | same annotation identity and output hashes |

This evidence supports the claim that the recent reviewer did not perform a one-line or first-page
only inspection. It recorded one cross-document comparison per observed Item and page-local
evidence across the entire supplied pair. It does not prove that every conclusion is educationally
correct; that remains a human quality judgment.

## Contract gaps found

### 1. Exhaustive criterion coverage is instructed but not fail-closed

The result requires at least one verification target and one cross-document check. It does not
require a target for every preset criterion, every review axis, every page, or every detected Item.
The recent result happened to include 25 cross-document checks and whole-document page coverage,
but a materially shallower result could still satisfy the released model.

The concrete live symptom is that dedicated `EDITORIAL_CLARITY` and `TYPOGRAPHY` targets are absent
even though the fixed instructions require detailed editorial inspection.

### 2. An insufficient verification target does not force human decision

The recent `ORIGINALITY` verification target is `INSUFFICIENT`, but the aggregate review status is
`COMPLETE`. The released semantic validator derives `NEEDS_HUMAN_DECISION` from an `UNCERTAIN`
candidate or an `INSUFFICIENT` cross-document check; it does not include an `INSUFFICIENT`
verification target. This is internally consistent with the current bytes but is weaker than the
intended fail-closed review meaning.

### 3. Item-level solve evidence is bounded but not a full structured solution report

The instructions require independent solving and the live result has 25 anchored cross-document
conclusions. The protocol deliberately does not store hidden chain-of-thought. It also does not have
a typed per-Item public verification record for answer derivation, condition use, unit checks,
distractor diagnostics, and explanation-step agreement. Therefore EOM can prove that comparisons
were recorded, but not mechanically prove that every detailed solve dimension was completed.

### 4. Graph-grounded document review is not yet the released paired-review contract

The paired successor uses the exact documents and the reviewed general-knowledge policy. It does
not yet run a bounded curriculum/topic planning step, retrieve a relevant Graph Evidence Bundle,
and persist evidence-use receipts for its scientific or originality judgments. ADR 0105 explicitly
keeps that as a later successor rather than attaching unrelated corpus evidence.

## Verdict

`RECENT_LIVE_REVIEW_DEPTH=PASS`

The recent result demonstrates broad practical review: whole-pair page coverage, 25 role-correct
question/solution checks, multi-axis verification, a confirmed located finding, and a portable
native comment-panel derivative.

`EXHAUSTIVE_DETAIL_CONTRACT=PARTIAL`

The current released contract cannot yet guarantee that every preset criterion and every Item-level
detail was covered, and it permits an insufficient verification target to coexist with aggregate
`COMPLETE`. The README and system-status claims must retain this distinction.

## Recommended protocol-first successor

Do not reinterpret result `@2.0` or historical Artifacts. Before changing worker behavior, define a
new JSON Schema 2020-12 and matching frozen Pydantic family with:

1. stable criterion codes instead of enforcing free-form preset strings;
2. a typed document-local Item roster with question and optional solution anchors;
3. one bounded public check record per Item for answer uniqueness, condition sufficiency,
   scientific reasoning, units/numerics, visuals/tables, explanation agreement, and editorial state;
4. exact coverage rules tying the roster, preset criterion codes, verification targets, and
   cross-document checks together in linear-time maps/sets;
5. `NEEDS_HUMAN_DECISION` whenever any required target or check is insufficient;
6. an orchestrator-mediated Graph planning and Evidence Bundle step before any Graph-grounded
   scientific/originality claim, plus immutable evidence-use receipts;
7. negative tests for missing criteria, duplicate Item keys, missing role anchors, page/hash drift,
   shallow coverage, insufficient-status downgrade, and stale/mismatched evidence.

The dominant access patterns are identity lookup, uniqueness/membership, ordered Item iteration,
and immutable history. The appropriate structures are keyed maps/sets for validation, tuples for
canonical output order, and existing indexed Artifact/Workflow relations. No new queue, binary DB
storage, direct worker communication, or worker NAS write is needed.

This successor is a separate implementation decision. The audit itself does not activate it or
change any runtime behavior.
