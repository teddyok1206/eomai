# Index private source archive compatibility

Status: SOURCE_IMPLEMENTED_NOT_REPUBLISHED; no root/NEW/prefix/model/GPU operation.

1. Responsibility/boundary: align the existing index-only NEW helper's bounded source
   leaf check with the original Git archive producer. Do not introduce an installer,
   resolver or authority port. Historical E5 main/model-only code stays unchanged.
2. Canonical source: exact retained full40 source commit/tar raw SHA, actual wheel and
   installed bytes. Existing source tar ba630f1ec9ea23e82030bf5390317bb40ae29f47 is 54,272,000B,
   raw SHA 24cf6b63eebf3fdc6a52ec8e43d19d7ca3ebc8a0ace47af4280cae225475160b. Read-only
   held/current byte diagnostic found 6,327 total members and matching Git PAX comment;
   original paths exist only beneath the exact full40 directory, not at archive root.
3. Identity/revision: source commit, tar raw hash, wheel raw hash and helper source raw
   hash remain distinct. Successor owner publication requires explicit commit/tar/helper pins;
   old d3cc5cb687b222d6d292439d60f945d37c91cb635fda8183d48008c0ea8b3d18 snapshots
   and old retained candidates are never overwritten/reclassified.
4. Resolution checks: the same existing helper supports either existing plain member
   names or an exact declared full40 root directory (size 0) plus descendants. PAX comment
   must equal declared commit. Pick one layout from first real tar member; strip only
   the exact prefix in that layout. Reject arbitrary/wrong/mixed prefixes, unsafe paths,
   normalized collisions, duplicate names and existing count/size violations. Index-only
   canonical relative names reject dot/doubled-separator/backslash spellings. Selected
   source leaves still must be regular and match exact wheel/installed bytes.
5. Access patterns: one ordered tar walk with keyed normalized-member lookup for the
   existing fixed source leaves. Wheel member membership/hash checks remain unchanged.
6. Structures: existing local dictionary only, plus one fixed layout value. No generic
   tar adapter, mutable registry, plugin, DTO or copied parser from Catalog.
7. Complexity/scale: O(tar members + fixed selected leaves), existing 20,000 member/
   64MiB per-member/1MiB selected-leaf/10,000 wheel limits. Do not extract or copy source
   archives or create another canonical artifact.
8. Transaction/concurrency: existing protected owner snapshot, profile flock, OLD whole-
   prefix audit, source/archive raw pins/epochs and root-maintenance drain remain required.
   This path normalization alone is neither first-instruction nor final native admission.
9. Ownership/dependency: only index-specific `_index_private_source` in existing helper,
   existing `test_embedding_index_runtime_installation.py`, and this purpose note. Frozen
   wheel/prefix core/source5, audit leaf, publisher, proof/schema and historical E5 remain
   untouched. No new dependency or private cross-service parser import.
10. Failure/retry/idempotency: plain in-memory producer lookup succeeds but prefixed lookup
    currently fails despite same PAX; actual source confirms this deterministic mismatch.
    Preserve old errors/byte comparison; missing/changed/link/extra-root/mixed/duplicate/
    traversal input fails, never substitutes latest or repairs bytes. Root's staged failed
    CPU/backup/phase/receipt/log stay preserved; explicit reviewed successor reassembly
    and existing publish are separate operational work, not an automatic retry.
11. Simpler alternative/tests: changing producer layout or copying leaves hides provenance
    and breaks existing immutable archives. Normalize the exact two already supported Git
    layouts at the owning consumer. Add platform/lease prefixed positives and plain
    compatibility, wrong comment/root/mixed/duplicate/path/type/bound/leaf negatives;
    retain historical helper AST/shell hashes, strict/style/focused/full18 source gates.

The authoritative OLD Catalog prefix audit validates all private Python/resources and
complete tree closure. NEW helper continues its bounded historical selected-leaf check;
this alignment does not advertise that older check as full-source authority. Until root
reviews/freezes this successor helper and its raw pins, the existing NEW instruction is
not claimed operationally aligned with the accepted prefixed source archive.

Source gates: exact platform/lease × plain/full40 positives plus 24 malformed-layout,
selected-leaf and bound cases; existing historical helper AST and shell raw hashes remain
unchanged. The index installation and historical CPU installation suites passed 278 tests
in 4.27s. The same shared eighteen-suite inventory recorded in the host boundary/source5
checkpoint passed 1188 tests in 32.96s. Explicit API Conda Ruff/format and core Conda strict
mypy (`--follow-imports=silent --explicit-package-bases`) passed both changed Python files.
These are synthetic source tests, not the retained helper, protected prefix, whole-prefix
audit, numeric proof, model/device benchmark, or runtime admission. A later explicit
successor snapshot and actual owner audit/publish remain required; failed CPU evidence and
original developer backup are not repaired, overwritten or automatically retried here.

Root independently reviewed the three frozen paths, matched their raw hashes and reran
the nineteen-suite inventory including the historical CPU installation tests: **1370 PASS
in32.98s, skip0**. Strict mypy, Ruff and format passed both Python files. Old accepted helper
snapshots remain unchanged; only a new reviewed owner snapshot can use the successor hash.
