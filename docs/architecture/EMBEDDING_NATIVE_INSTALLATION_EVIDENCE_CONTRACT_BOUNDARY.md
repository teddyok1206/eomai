# ROOTLOCAL installation evidence metadata — pure source boundary

2026-10-13 UTC. SOURCE_ONLY / NOT_ADMITTED / NOT_PUBLISHED.

This leaf implements the two already written, unregistered protocol drafts. Parsing, constructing
or serializing these values does not observe a prefix, attest a native unit, seal a candidate or
authorize an operator, source, Job, INDEX/QUERY purpose, benchmark or runtime. There is no admission
adapter, filesystem reader, unit launcher or candidate-to-sealed transition in this scope.

## Eleven decisions

1. **Responsibility:** Add one Catalog contracts module for frozen ROOTLOCAL candidate-inventory
   and sealed-receipt *metadata*, two fixed raw parsers and supplied-reference validation only.
2. **Canonical source:** Keep the reviewed `.schema.proposal.json` bytes outside
   worker schema registration. The owner supplies those exact raw schema bytes to the pure parser;
   fixed independent source SHA checks precede decoding/checking the whole JSON Schema 2020-12.
3. **Identity:** Preserve configuration logical/revision IDs, inventory raw/semantic SHA, receipt
   raw/semantic SHA, owner-input/host pins and existing proof/bundle/runtime pins separately.
   Semantic inventory/receipt hashes exclude only their own hash field. No authority boolean.
4. **Resolution:** Check canonical raw evidence and independently supplied receipt raw pin, then
   close receipt→inventory/config/proof/bundle/runtime through existing public pointer validators.
   Candidate state remains CANDIDATE_NOT_ADMITTED. Actual audit/probe origin is still owner work.
5. **Access patterns:** Bounded byte decoding, ordered immutable entries, member-key uniqueness,
   count/size consistency and a constant number of exact metadata-reference comparisons.
6. **Structures:** Frozen typed tuples/value models and linear set/map checks; no large arbitrary
   dict payload, parallel registry, cache, schema/plugin framework or dynamically selected parser.
7. **Bounds/cost:** Inventory ≤16 MiB, ≤100,000 entries; receipt ≤32 KiB; raw nesting ≤16 and integer
   lexemes ≤20 characters before JSON allocation. Reject duplicates, floats/NaN, extra fields,
   wrong raw integer types, copied/constructed extras, unsafe names and invalid UTC. O(bytes +
   entries + total relative-name length), with no filesystem scan/hash or quadratic uniqueness.
8. **Concurrency:** Pure metadata only. Frozen references cannot replace the real publication
   reservation, current host/prefix/FD epochs, unit invocation/process identity or termination.
9. **Dependencies:** Reuse canonical/SHA helpers, FrozenModel, public Catalog registry only for
   existing proof/bundle `$ref` resolution, and existing config/proof/bundle reference validators.
   The existing bounded native-config decoder is private and purpose-fixed; the public similarity
   reader's 1,024-array bound cannot cover this 100,000-entry inventory. A small private bounded
   decoder shared by these two real documents is the minimal missing seam, not a framework.
10. **Failure:** Stable content-free parser/reference errors; no fallback latest, repair, retry,
    evidence publication or seal. UTC receives actual calendar/timezone validation, not reliance
    on an optionally absent RFC3339 format checker. Direct frozen construction is also revalidated.
11. **Alternative:** Reusing a production worker parser or adding these drafts to its registry
    misstates activation. A self-hashed PASS cannot prove origin. Fixed unregistered metadata
    validation leaves actual root observation and independently accepted raw pins where they belong.

## Fixed drafts and API limits

Current raw SHA-256 (unprefixed here only for source freeze bookkeeping):

- `embedding-native-prefix-inventory-v1.schema.proposal.json`:
  `1c9c8b2a05fe8534e95b4955a8111f4882138b70b7374dd93d0770558b1f21d1`.
- `embedding-native-admission-receipt-v1.schema.proposal.json`:
  `210b56190b6c71a7c49f6ae290d5dc3c206fdfb9f5c36745ea7aa271e2d1cd1f`.

The fixed schema reader permits the original pretty schema bytes/newline after exact raw-pin
verification; only evidence documents require exact canonical bytes. Installed proof/bundle
resources are resolved through the existing public immutable registry, never mutated or registered
under these new local IDs. No filesystem path or IO/subprocess method is accepted by this module.

Inventory entries retain declared root-owned epochs/kind/hash/link fields and sorted unique
relative names. Check shape/mode/link/count/size consistency and required parent directories without
pretending to reproduce source/ELF audits. Their four audit digests remain opaque supplied metadata;
an ELF count may be checked against regular count but pixels/ELF bytes were not read by this leaf.

The receipt is CPU-first, records exact successful terminal/no-model probe metadata and requires
seal time not before termination. These remain declared values, not observed facts. Independent
raw-pin validation and reference closure are necessary metadata checks, not sufficient runtime
admission. An ordinary Python caller can construct syntactically correct evidence; no API name or
serializer here claims that a candidate has become genuinely sealed.

Owned source scope is exactly the new contracts module, its focused test and this separate note.
The original proposal note is concurrently owned elsewhere and is not edited. Protocol drafts,
worker resource inventory, public package exports, existing models, runtime, database, permissions,
Git writes, installation and actual evidence publication remain outside this source leaf.

## Source checkpoint

The first actual CPU export subsequently measured30,669 entries and8,651,841 bytes for entries
alone. Before any accepted inventory existed, the unpublished inventory draft's byte bound was
corrected from8MiB to16MiB and its raw pin above updated. All fields and other limits remain
unchanged. The receipt draft and every released schema remain unchanged. The original inventory
draft raw SHA was `9164de1dac4bae369b47a79436432440bf5f1ec26b2d7b7f35ec21824090e9f0`;
the source checkpoint below records that historical gate, not a16MiB installed acceptance.

The two fixed parsers now verify the complete original draft raw pins, use their JSON Schema
2020-12 shapes and existing proof/bundle `$ref` registry, and enforce exact canonical evidence.
The frozen models preserve raw copied/constructed fields, strict epoch/unit integer types,
sorted unique member names, kind/hash/link/count/size consistency and actual UTC calendar/order.
Supplied-reference closure independently checks complete receipt raw bytes and separate inventory,
configuration, proof and bundle raw/semantic/revision/runtime pins through existing public seams.
Candidates remain NOT_ADMITTED, including a correctly parsed CUDA candidate. No model or method
seals a candidate, observes an installed prefix/unit or satisfies production `assert_current`.

Final exact five-suite SOURCE regression is **442 PASS in 5.71s** in the explicit API Conda and
**442 PASS in 5.76s** in the explicit core Conda, skip zero in both. These are the same inventory,
not 884 independent cases. Suites under `tests/unit/`: `test_embedding_native_installation_evidence`,
`test_embedding_native_runtime_config_contracts`, `test_embedding_installed_runtime_proof`,
`test_embedding_runtime_bundle_contracts`, `test_inference_transfer_embedding_contracts`.
Strict mypy **two paths PASS in each environment**; API Ruff lint and format **two paths PASS**.
Final gates use unchanged Python bytes and the original two draft raw SHAs remain exact.

Earlier 101 PASS and 440 PASS gates predate two review corrections and are not final freeze
evidence. A missing installed `$ref` reproduced one failure: JSON Schema wraps the public
`referencing.Unresolvable`; that exact public exception now yields a content-free metadata error,
without fallback resources, registration or broad catches. Independent full read found that an
initial directory-set equality rejected a valid empty DIRECTORY entry. A draft-valid empty-dir
positive reproduced one failure. Collecting every entry's immediate parent and requiring it in
the directory set now preserves empty directories and rejects missing directory parents in linear
name-length work. Existing same-audit prefix-export rules and all other owner modules were not
modified. Initial strict annotations/formatting issues were fixed before final gates.

Tests include schema raw-pin override, missing `$ref`, canonical/duplicate/extra/hash/UTF-8/floating/
NaN input, allocation-before-JSON size/depth/integer bounds, every unit integer's bool negatives,
epoch/kind/root ownership/range/count/path/UTF-8/parent checks, UTC/calendar/terminal/no-model CPU
claims, copied/constructed root/nested fields, raw-versus-semantic/revision closure and IO/import
boundaries. A 1,100-entry fixture exceeds the unrelated similarity-reader array limit without
changing that helper; a 100,001-entry raw model is rejected before materialization. Declared UID0
epochs/unit facts in these synthetic values are not mocked actual observations or root authority.

Actual same-audit provenance, current protected named/FD/ancestor epochs, host/boot/device capture,
independent unit negatives/loaded maps/termination, accepted owner raw pins and native admission
composition remain mandatory later gates. No protected file, schema registry, public export,
database, Artifact, runtime, model/GPU or privileged state was changed by this source leaf.
