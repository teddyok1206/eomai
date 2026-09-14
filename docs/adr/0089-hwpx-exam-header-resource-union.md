# ADR 0089: Deterministic HWPX exam header resource union

## Status

Accepted. This supersedes the merge rule in ADR 0078 while preserving its fail-closed shared-
template boundary.

## Responsibility and canonical source

The whole-exam HWPX adapter renders each approved Item Revision into one temporary HWPX package,
then combines those packages into a derived exam Artifact. The approved Item Revisions and their
pinned component Artifact Revisions remain canonical. Per-Item packages and the combined package
are bounded materializations; no HWPX or image bytes are stored in PostgreSQL and only the
orchestrator may commit the validated final Artifact to NAS.

The reviewed renderer can append paragraph, character, tab, and style resources for inquiry,
table-alignment, and visual layouts. Two valid Items can therefore branch from the same template:
one header may add resources while another changes a style with the same local numeric ID to point
at an added paragraph resource. The append-only-superset rule in ADR 0078 rejects that valid pair.
Selecting either header without rewriting references would silently change the other Item.

## Decision

1. The header outside the four renderer-owned resource catalogs (`tabProperties`,
   `charProperties`, `paraProperties`, and `styles`) must remain byte-equivalent after canonical XML
   serialization, apart from the final section count. Catalog placement, namespace, attributes,
   and ordering are part of that comparison. Every catalog has unique non-negative numeric IDs and
   an exact `itemCnt`.
2. Build one deterministic resource union in dependency order: tab and character properties,
   paragraph properties after remapping tab references, then styles after remapping character and
   paragraph references. Definitions are interned by canonical XML bytes with only their own local
   ID normalized. Existing IDs are preserved when possible; a collision receives the next unused
   numeric ID. The ordered Item position is the deterministic tie-breaker.
3. Rewrite each copied section's exact `tabPrIDRef`, `charPrIDRef`, `paraPrIDRef`, `styleIDRef`, and
   `charStyleIDRef` values through that Item's maps. Style self-references follow the allocated
   style ID. A non-self style edge may be retained only when its target remains identity-mapped;
   a future renderer that needs a branching style graph must introduce an explicit successor rule
   rather than being guessed here.
4. Validate every source and rewritten reference against its respective catalog. Unknown IDs,
   duplicate IDs, malformed counts, non-numeric IDs, changing static header data, or an
   unsupported cross-style remap fail before the final ZIP is committed. Other shared package
   members remain byte-exact as required by ADR 0078.

## Access pattern and data structures

The dominant operations are ordered iteration, ID lookup, semantic deduplication, and reference
rewriting over at most 200 Items. Per-catalog dictionaries map source ID to output ID and canonical
definition bytes to output ID; sets track allocated IDs. The merge is O(R + S) time and O(R) space,
where R is the total number of header resource definitions and S is the total number of section XML
nodes. It avoids repeated list scans and preserves stable Item and section order. Header resources
are small, immutable XML value objects with no independent lifecycle, so a database model or cache
would add no value.

## Transaction, concurrency, failure, and retry

Input ZIP members are already bounded and parsed without external entity expansion. The union and
section rewrites occur only in the isolated builder workspace. The builder writes a fresh
same-directory temporary ZIP, structurally validates it, and atomically replaces the output.
Failure leaves the prior immutable build attempt and its stable error untouched. A retry must use a
new supported build attempt against the same pinned Assembly Revision; it never edits the failed
row or resolves an implicit latest revision. Deterministic IDs and archive timestamps make replay
byte-identical for the same ordered inputs.

## Simpler alternative and trade-off

A universal maximal header would avoid merge logic but would couple every Item render to all layout
branches and require a handoff release whenever any branch changes. Choosing one existing header is
shorter but is incorrect when valid branches reuse a local ID. General XML graph isomorphism would
support hypothetical cyclic style graphs but is unnecessary for the two real renderer branches and
would obscure the failure boundary. The bounded typed-catalog union is the smallest implementation
that safely supports the observed inquiry, table, and image layouts.
