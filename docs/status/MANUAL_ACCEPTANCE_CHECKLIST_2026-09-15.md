# Deferred Manual Acceptance Checklist — 2026-09-15

This is the single collection point for observations that require a human eye or an educational
judgement while the development roadmap is running. Automated work continues without interrupting
the user for each observation. At the end of the roadmap, the remaining unchecked observations are
presented together in one short review session.

This document does not authorize a state change, approve an Item, or replace an automated contract
gate. A checked box must include the observer, UTC time, visible product identity, and a concise
outcome. Do not record Item content, credentials, cookies, prompts, or private storage paths here.

## Gate A: Scientific Studio in a real browser

- [ ] Open a current approved table-only Item. Confirm that the data remains an editable table,
      there is no empty image frame, and no invented `(가)` label appears.
- [ ] Open a current approved paired-image Item. Confirm that two different images render in authored
      order and `(가)` / `(나)` are associated with the correct panels.
- [ ] Open a current approved mixed-material Item in each available authored order. Confirm that an
      image and a table remain separate semantic blocks and that no paired label is invented.
- [ ] Switch rapidly from Item A to Item B. Confirm that a late response for A never replaces B and
      that stale edit/download targets disappear.
- [ ] Refresh the Item and HWPX lists, then log out and back in. Confirm that loading, empty, denied,
      expired-session, and unavailable-preview states give an actionable Korean message rather than
      a generic API error.
- [ ] When a safe failed or denied request is visible, confirm that it shows one inquiry number that
      an administrator can correlate, without showing a payload, path, prompt, or Item content.
- [ ] With a role that lacks access, confirm that Item media and administrator details are not shown.

## Gate A: exact whole-exam HWPX in Hancom

Automated baseline: build `hwpxbuild_da626008bbc14afc9d3408bc0107a0f9`, 25 Items, output SHA-256
`sha256:5f1ab03c1123957c6bd550a9b2e9bfd73030fa40bbdcf70e6433d757e1f22bab`.

- [ ] Download the exact build through Scientific Studio and open it in Hancom without a repair or
      corruption warning.
- [ ] Confirm that PNG bytes are embedded in the package: images remain visible after moving the
      HWPX to a different local directory or disconnecting from the site.
- [ ] Confirm that a single table has no image placeholder; two tables have editable `(가)` / `(나)`
      text in their own cells.
- [ ] Confirm that one image has no panel label; two images occupy separate cells and their `(가)` /
      `(나)` labels are editable text rather than rasterized pixels.
- [ ] Inspect mixed image/table Items and confirm authored order, spacing, borders, and captions.
- [ ] Inspect equations, choices, explanations, page breaks, headers/footers, and the transition
      between consecutive Items for clipping, overlap, or unexpected blank pages.
- [ ] Save a copy after one harmless text edit and reopen it to confirm normal editability.

## Gate B: educational and workflow review

- [ ] Use the exact frozen cohort and rubric in
      [M02 25-Item Educational Review Baseline](M02_25_ITEM_EDUCATIONAL_REVIEW_BASELINE_2026-09-15.md);
      do not substitute current Item revisions.
- [ ] Review all 25 baseline Items for scientific correctness, unique answer, evidence relevance,
      visual consistency, authoring value, and required edit time.
- [ ] Have a second content lead independently review at least the agreed sample; record disagreements
      without averaging away a critical error.
- [ ] For every Item marked publishable, confirm zero unresolved critical scientific or visual error.
- [ ] Record whether the evidence actually supports the applied claim or structure; receipt integrity
      alone is not educational approval.
- [ ] Record edit disposition (`no edit`, `minor`, `major`, or `discard`) and elapsed human review time
      using the existing review/rating boundary.

## Gate C: limited textbook-evidence pilot

- [ ] Confirm source-use permission, exact source revision, page/anchor visibility, and access-policy
      behavior for the limited pilot corpus.
- [ ] Compare past-exam-only and textbook-assisted outputs using the same educational rubric and
      confirm whether the textbook evidence materially improves correctness or scope.
- [ ] Confirm that a mixed-source successor never silently changes a released past-exam-only plan.

## Final operational review

- [ ] Open the administrator operational details panel. Confirm that executable work, pending human
      approval, quiescent non-terminal history, and recent/historical failures are visually distinct.
- [ ] Confirm that technical IDs remain hidden from the default user view and appear only after the
      administrator detail is deliberately opened.
- [ ] Confirm that the administrator view separates a current actionable failure, historical terminal
      failure, and retired transient unit state.
- [ ] Follow one UI correlation ID to its immutable Workflow, Job, Artifact Revision, receipt, and
      stable error code without exposing content or secrets.
- [ ] Review the final installed component/release map, rollback locations, capacity evidence,
      recovery result, known unknowns, and next explicitly authorized task.

## Observation record

Add observations here only when the manual review is performed.

| UTC time | Observer | Gate/case | Visible identity | Result | Concise observation |
| --- | --- | --- | --- | --- | --- |
