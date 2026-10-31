# Registered creative Item DB parity

User-facing categories are PAST_EXAM / CREATIVE / AI. Approval is an independent
filter and per-row value, never a category. CREATIVE retains imported rows before
registration (UNREGISTERED) and enriches them with the canonical registration once
available; all 32 metadata predicates remain available before and after approval.
AI includes pending human review as well as approved generated revisions. Graph
capability is a separate optional validated pointer, not inferred from approval.

## Responsibility and identity

The DB screen retains Catalog's source metadata read boundary and enriches it with
the exact canonical registration revision. Registry reads include pending human
approval; they do not assert that a Graph analysis has already been published.
Semantic similarity and registered assembly still resolve through the existing
published Graph production-candidate boundary; archive rows are not promoted into Items.
Creative means the existing `creative-source:<source_id>` registration and its
CREATIVE metadata/source-revision relationship. AI means a canonical Item created
by `generic-item-development`, not merely any APPROVED_ITEM Graph source.
Unclassified Items are not silently labelled AI or creative.

## Resolution and data flow

The candidate retains Graph revision/hash, Item revision/manifest hash and analysis
identity. Creative metadata resolves source ID + immutable revision + external
number through the Catalog source tables and completed import. Original cells,
files and PDF actions reuse the existing authenticated source read boundary.
If the original source's current revision has changed, detail fails explicitly;
it never displays latest metadata as though it belonged to the approved Item.
Approval state comes from the canonical Item revision. Curriculum and supported
registered assembly actions remain validated Graph candidate data.
Original-file actions remain source actions; they are not the approved Item output.

## Search and concurrency

Apply the same ALL/ANY, 32-column and file-status predicates in SQL before Graph
pagination. Reuse Catalog's metadata predicate implementation. Indexed revision
and source identity joins/EXISTS prevent per-row metadata fetches and duplicate
candidate rows. Page enrichment uses one bounded source query and a keyed map.
The existing unique registration-key index bounds source-to-Item lookups before
metadata identity checks. No migration, new index, queue, artifact copies or model execution is required.
At current thousands-of-Items scale, metadata predicates have the existing JSON
predicate cost; Graph population, source revision PK and Item identity remain
indexed. Cursor scope includes kind, predicates and immutable Graph snapshot.

Approval changes between the two bounded source/enrichment reads fail explicitly
instead of returning a row that no longer matches the chosen approval filter.
Reads own no state transitions or retries. Existing session/RBAC/CSRF and signed
cursor validation apply. Creative metadata requires CONTENT_INTAKE_READ as well
as ITEM_READ; AI/past-exam readers do not gain source permissions. UI sequence
guards prevent late original detail from replacing a newly selected Item.

## Alternatives

Filtering a downloaded page in JavaScript loses matching results and breaks
pagination. Copying original metadata into Item rows creates a second authority.
Both are rejected. Existing production-candidate wire contracts remain unchanged;
the DB-specific wrapper is additive, schema-first and independently testable.
