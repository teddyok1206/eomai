# Content-team authoring prompt V5 design

## Boundary and canonical source

The content team's 52,274-byte Markdown is untrusted reviewed reference input. V5 preserves its
exact bytes and SHA-256 as a CONFIG reference and materializes it into authoring and review worker
workspaces. The released instruction-bundle revision, not the Markdown itself, remains execution
authority.

## Identity and access pattern

The source prompt, typed Markdown adapter, instruction bundle revision, and output item revision are
separate immutable identities. Runtime access is one hash-checked key lookup by `reference_key`;
roles receive a keyed reference bundle rather than copied prompt text inside requests. Five small
references are bounded well below the existing 512 KiB member limit, so lookup and verification are
O(1) per reference and storage is O(reference bytes) per immutable bundle revision.

## Transaction, failure, and compatibility

Bootstrap publishes all reference artifacts before the V5 preset can be released. Missing files,
hash drift, unsafe paths, unused references, or a changed role-reference map fail before runtime.
V5 retains workflow-role/1.13.0 because the worker protocol is unchanged; only the immutable
instruction/reference bundle revision advances. Replaying identical V5 inputs is idempotent through
existing content hashes and bootstrap keys.

## Output adaptation

The source prompt's HwpQuestionEditor Markdown rules are projection requirements, while canonical
AssessmentItemContent remains presentation-neutral. Decimal `2.5` scoring is not representable by
the current integer score contract and therefore fails explicitly instead of being rounded. A later
decimal-score protocol revision must update item, preview, authoring, and HWPX schemas together.

The simpler alternative—mentioning the staging path from an instruction—was rejected because worker
workspaces cannot access staging and it would not pin bytes, provenance, or revision identity.

## 2026-11-11: mandatory grounding for new authoring

The team reference files remain byte-for-byte unchanged. New authoring admission belongs to the
API command application, not the checkbox or the worker. The Web form has no general-knowledge
choice; it resolves the API-owned current corpus and uses the existing knowledge preset. Saved
drafts retain their old DTO/hash for reading, but a false historical flag never authorizes a new
ungrounded execution. The application returns an exact existing Workflow replay before applying
the new admission rule; running and completed execution pins are not rewritten.

For a fresh generated Item, an explicit Graph requirement including TEXTBOOK is mandatory. Catalog
owns actual selection: at least one authorized, non-answer-bearing textbook grounding entry must
fit the released evidence budget before any new Evidence Artifact is committed. Missing coverage
is a preparation error, never a general-model fallback. The existing exact Graph/policy/source
revision, Artifact member/hash, permission and lifecycle resolution remains authoritative.

Access patterns are one indexed replay lookup, bounded Graph retrieval, a linear pass over bounded
candidates/entries, and an indexed Evidence-revision membership check. The first ranked textbook
that fits the budget is reserved before optional pattern references; final published ordering remains score/ID order.
Catalog reuses `KnowledgeGraphPublicationService.resolve_accepted_analyses` for up to three ranked
textbook analyses. It checks the selected Graph's accepted-result/source/anchor pins, then includes
bounded approved analysis text and its immutable pointer in context.md. Graph labels alone are not
textbook content. This is approved analysis, not a claim of verbatim PDF reading or visual inspection.
The whole context retains its existing byte/token budget. Old labels-only prepared contexts fail
explicitly for new textbook-required starts; their bytes and completed Workflow replays stay intact.
No new DB table, cache, queue, worker communication channel, binary copy or search engine is needed.
Publication keeps its existing transaction, immutable manifest, unique idempotency key and race
resolution. Repeated preparation rechecks the original selected textbook metadata, without changing
or silently replacing the original Evidence snapshot.

Released exact-variation V2 remains PAST_EXAM-only for historical replay/read/resume. Its additive
V3 successor pins the same one source Item Revision and the selected curriculum root, and permits
only that past-exam Item plus authorized textbook context. Workflow-start V7 and Catalog request
V20 carry it; execution-plan V35/V36 preserve the existing post-registration/public-similarity
paths. Other past-exam Items are not silently substituted. Existing production contracts are not
rewritten; unsupported new past-only starts fail explicitly.

The smaller UI-only change is insufficient: direct API callers can bypass it, and listing TEXTBOOK
as an allowed source does not prove a textbook was actually selected. New generated starts require
the exact generated-knowledge-item 1.20.19 release hash. Its separate authoring/review integration
instructions require actual textbook use; the existing evidence-usage verifier checks a textbook
grounding citation and review links to textbook evidence. The guard is selected by immutable Pack
hash, never applied retroactively to old results. This verifies evidence linkage, not the scientific
or educational correctness of the model's judgment. The two team-owned source prompts are unchanged.

For Preview, CONTENT_TEAM_V2/V3 already include the complete correct/wrong statement explanations
in the main explanation. Render that representation once, retaining the statement DTO for identity
validation. BLOCKS_V1 may have independent overview and statement explanations and keeps both.
Canonical content and HWPX serialization are not altered.
