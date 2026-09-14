# ADR 0078: HWPX whole-exam append-only header superset merge

## Status

Superseded by ADR 0089. The shared-template and atomic-output boundaries remain in force; ADR 0089
replaces only the append-only header selection rule with deterministic typed resource union and
section reference remapping.

## Context and responsibility

The whole-exam HWPX builder renders each approved Item with the reviewed template branch that
matches its material layout and then combines the resulting sections.  A text-only or native-table
branch can use the base `header.xml`, while another reviewed branch can append a paragraph style to
the same immutable header tables.  Requiring every per-Item header byte to be identical therefore
rejects a legitimate exam that mixes material forms.  Blindly selecting one header is unsafe
because a section may then reference a style that is absent or has different semantics.

The approved Item Revision and its component pointers remain canonical.  Each per-Item HWPX is a
temporary materialization.  The final whole-exam Artifact is a new immutable revision and does not
replace or duplicate any canonical Item content in PostgreSQL.

## Decision

1. Treat HWPX header resource collections as ordered, append-only tables.  A candidate header
   covers another header only when their XML is identical recursively, except that `secCnt` may
   differ and an element with `itemCnt` may contain additional children strictly after an exact
   common prefix.
2. Select one existing per-Item header that covers the current selection while scanning the
   ordered Items.  If neither header covers the other, fail closed; do not merge or renumber
   incompatible definitions.
3. Exclude `Contents/header.xml` from the byte-identical shared-member comparison, then verify every
   Item header is covered by the selected superset.  All other shared members remain byte-exact.
4. Set only the selected header's final section count and preserve its compression method.  Section
   resource references need no remapping because prefix identity proves that every referenced
   existing ID retains the same definition.

The dominant operations are ordered iteration over at most 200 Items and recursive comparison of
bounded XML trees.  The implementation keeps one parsed selected header plus one current header, so
selection is O(nh) time and O(h) auxiliary space for `n` Items and header size `h`.  A map or DB
index does not improve this append-only compatibility check; ZIP member lookup already uses the
package's keyed collection.

## Transaction, failure, and retry

Input packages are bounded, safely parsed, and never trusted by path alone.  Missing headers,
invalid `itemCnt`, non-prefix additions, changed shared definitions, or incomparable headers return
the existing stable structural-validation error before the final archive is committed.  Archive
creation remains a fresh same-directory temporary write followed by validation and atomic replace.
Retries are deterministic for the same pinned Item revisions, renderer inputs, and handoff hashes.

This is an HWPX projection-adapter rule.  It adds no worker communication, NAS write, database
mutation, schema dependency, or cross-layer import.  The orchestrator-owned manager remains the
only component that may commit the validated output Artifact to NAS.

## Alternatives

Requiring one universal template header would make every material branch carry unused definitions
and would require a new handoff release whenever one branch gains a style.  General union and ID
renumbering would accept incomparable headers but introduces reference rewriting across sections
and every header resource family.  The append-only superset rule is simpler and sufficient for the
reviewed templates while explicitly rejecting the unsafe case.
