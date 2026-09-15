# M02 25-Item educational review baseline

Status: `PREPARED_FOR_HUMAN_REVIEW`

Evidence time: 2026-09-15 13:35 UTC

This is the frozen evaluation worksheet for the existing V5 25-Item technical-acceptance cohort.
It does not create, revise, approve, or reject an Item. Blank cells are pending human observations,
not missing technical evidence.

## Immutable evaluation target

| Field | Value |
| --- | --- |
| Assessment Assembly | `assembly_f0aa37b8aa950bc601982919a415fafc` |
| Assembly Revision | `assemblyrev_f42d6a195e07f21221d24baea250f0c4` |
| assembly manifest SHA-256 | `sha256:afc041c19c11be1f2d94839abeec508c6c0d99cdd6576511874c18be85fe1918` |
| Item-set SHA-256 | `sha256:d67d2f4941ad26e45d97b615ae4d202cb57bb651991cbc13077c6191fe283780` |
| latest embedded-image build | `hwpxbuild_da626008bbc14afc9d3408bc0107a0f9` |
| HWPX output SHA-256 | `sha256:5f1ab03c1123957c6bd550a9b2e9bfd73030fa40bbdcf70e6433d757e1f22bab` |

The Assembly contains exactly 25 approved immutable Item Revisions from Workflow 1.10 and Content
Pack release `packrel_0ebfaa4c7db14ed08ae63d4e17fc9d2a`. The review must stay pinned to these
revisions. A later current Item Revision must not silently replace one of them.

The existing production rating is `C` for all 25 Items. That value is an assembly-eligibility rating
under `integrated-science-item-rating/1.0`; it is not evidence that all Items have the same scientific
quality, editing cost, or publication readiness. M02 observations remain a separate human product
evaluation and must not rewrite the immutable production decision.

## Coverage baseline

| Dimension | Distribution |
| --- | --- |
| material | TEXT 7, DATA 5, TABLE 4, MIXED 5, INQUIRY 4 |
| requested difficulty | LOW 8, MEDIUM 9, HIGH 8 |
| inquiry | 4 inquiry, 21 non-inquiry |
| major curriculum unit | large.1 4, large.2 4, large.3 6, large.4 4, large.5 4, large.6 3 |

At least one content lead reviews all 25. A second content lead independently reviews the following
stratified ten positions: `1, 3, 5, 8, 11, 12, 16, 18, 21, 23`. This sample covers all five material
profiles, all six major units, all three requested difficulty bands, and multiple inquiry Items.
Critical disagreements are resolved explicitly; they are never averaged away.

## Rating instructions

For each Item, inspect the Scientific Studio Preview and the exact whole-exam HWPX section. Record:

- scientific correctness: integer 1–5 and whether a critical error exists;
- unique answer: `PASS`, `FAIL`, or `AMBIGUOUS`;
- evidence relevance: integer 1–5 after opening the cited source and confirming that it supports the
  applied claim or structure;
- authoring value: integer 1–5, distinguishing a useful assessment idea from superficial wording
  substitution;
- visual consistency: integer 1–5 or `N/A`, checking statement, units, labels, table, and image
  together;
- edit disposition: `NO_EDIT`, `MINOR`, `MAJOR`, or `DISCARD`;
- elapsed human review/edit time in whole minutes; and
- a short reason without copying full Item content or evidence text into this status document.

An Item is individually publishable only when it has unique-answer `PASS`, no unresolved critical
scientific or visual error, and a human disposition other than `DISCARD`. Aggregate averages never
override this per-Item gate.

## Review worksheet

| Pos. | Material | Difficulty | Unit | Second review | Scientific 1–5 | Critical | Unique answer | Evidence 1–5 | Value 1–5 | Visual 1–5/N/A | Disposition | Minutes | Short reason |
| ---: | --- | --- | --- | --- | ---: | --- | --- | ---: | ---: | --- | --- | ---: | --- |
| 1 | TEXT | LOW | large.1 | yes |  |  |  |  |  |  |  |  |  |
| 2 | TEXT | LOW | large.1 | no |  |  |  |  |  |  |  |  |  |
| 3 | INQUIRY | MEDIUM | large.1 | yes |  |  |  |  |  |  |  |  |  |
| 4 | TEXT | LOW | large.1 | no |  |  |  |  |  |  |  |  |  |
| 5 | DATA | LOW | large.6 | yes |  |  |  |  |  |  |  |  |  |
| 6 | INQUIRY | MEDIUM | large.6 | no |  |  |  |  |  |  |  |  |  |
| 7 | TEXT | LOW | large.6 | no |  |  |  |  |  |  |  |  |  |
| 8 | TABLE | MEDIUM | large.2 | yes |  |  |  |  |  |  |  |  |  |
| 9 | DATA | MEDIUM | large.2 | no |  |  |  |  |  |  |  |  |  |
| 10 | TEXT | MEDIUM | large.2 | no |  |  |  |  |  |  |  |  |  |
| 11 | MIXED | HIGH | large.2 | yes |  |  |  |  |  |  |  |  |  |
| 12 | DATA | MEDIUM | large.3 | yes |  |  |  |  |  |  |  |  |  |
| 13 | MIXED | HIGH | large.3 | no |  |  |  |  |  |  |  |  |  |
| 14 | TABLE | HIGH | large.3 | no |  |  |  |  |  |  |  |  |  |
| 15 | TEXT | LOW | large.3 | no |  |  |  |  |  |  |  |  |  |
| 16 | INQUIRY | HIGH | large.3 | yes |  |  |  |  |  |  |  |  |  |
| 17 | MIXED | HIGH | large.3 | no |  |  |  |  |  |  |  |  |  |
| 18 | TABLE | MEDIUM | large.4 | yes |  |  |  |  |  |  |  |  |  |
| 19 | DATA | LOW | large.4 | no |  |  |  |  |  |  |  |  |  |
| 20 | TABLE | MEDIUM | large.4 | no |  |  |  |  |  |  |  |  |  |
| 21 | INQUIRY | HIGH | large.4 | yes |  |  |  |  |  |  |  |  |  |
| 22 | TEXT | LOW | large.5 | no |  |  |  |  |  |  |  |  |  |
| 23 | MIXED | MEDIUM | large.5 | yes |  |  |  |  |  |  |  |  |  |
| 24 | MIXED | HIGH | large.5 | no |  |  |  |  |  |  |  |  |  |
| 25 | DATA | HIGH | large.5 | no |  |  |  |  |  |  |  |  |  |

## Technical identity appendix

The UI should normally present position and content, not these IDs. They remain here only so an
administrator can prove that a review refers to the frozen Item Revision rather than mutable
current state.

| Pos. | Item Revision |
| ---: | --- |
| 1 | `itemrev_adcd14664ea442e4a6e92a673a33ba74` |
| 2 | `itemrev_26c885b808cd4a42ba7126a2217e04cd` |
| 3 | `itemrev_172254513d9d43789d57b7667a17e674` |
| 4 | `itemrev_9d4785defa9e40b0ba3c7be0ee3c2169` |
| 5 | `itemrev_18e5dd35a4eb4f94959ad01ad854444f` |
| 6 | `itemrev_b6ff28fd37174d20a8fa7baf8b81580f` |
| 7 | `itemrev_625d371cb8a94b53bc0ffb9974938767` |
| 8 | `itemrev_c51d24e6db6f44829a9eb4228adf7f47` |
| 9 | `itemrev_fc98ebb4ec6e411ca1d24d6a77e9c703` |
| 10 | `itemrev_1abe75f3bffb490186db0bf324895bf4` |
| 11 | `itemrev_92ce197ac2514cbc86db5530ed1714d2` |
| 12 | `itemrev_e6d97e4091ae4c8ebeed44ecd690442c` |
| 13 | `itemrev_c28feecd55e44c4dadd8e0ce4be27894` |
| 14 | `itemrev_b3c8fabb3f2a49b0ab446732e8968966` |
| 15 | `itemrev_570eebd353734be18857d7ec07a2a85a` |
| 16 | `itemrev_e069507769954486b10dad4556c4ba1a` |
| 17 | `itemrev_86fe2b0b50624d3faba867e78764b735` |
| 18 | `itemrev_62a86952a8dd4b86810a9c18ca4edb07` |
| 19 | `itemrev_e471a7400fdf4df88ea7510b5623f66e` |
| 20 | `itemrev_a0411afddd614c129d7f7941fe5148bc` |
| 21 | `itemrev_7fb5611d83154ae1999d7a995b9507b7` |
| 22 | `itemrev_764baccbea0549669d519e465a3300a7` |
| 23 | `itemrev_c43a8a2cf9d048d0b451d2c4f3bb55ea` |
| 24 | `itemrev_cf0ddecf27fe4a208e2f5cfbd81cce12` |
| 25 | `itemrev_f6c5aa52640a4ace891ea17596acb180` |

## Completion evidence

M02 is complete only when all 25 primary observations, the ten independent second observations,
critical-disagreement resolutions, and edit times are recorded against this exact target. The final
report must disclose reviewer coverage and missing observations. Technical acceptance, RAG receipt
integrity, and the existing `C` eligibility ratings are supporting evidence, not substitutes for
those human judgments.
