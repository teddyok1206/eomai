# Installed wheel layout compatibility

Status: SOURCE_PASS / ACTUAL_WHEEL56_PASS; whole-prefix/native admission and NEW pending.

1. Responsibility: correct the existing retained-wheel/installed-member verifier, not the
   installer, package resolver, runtime permission or model factory.
2. Canonical source: the exact owner-retained wheel archive and root distribution RECORD;
   installed bytes, metadata and epochs must agree with that archive.
3. Identity: distribution name/version, wheel raw SHA, installed RECORD raw SHA and runtime
   revision remain separate. Vendored metadata is payload, not another installed distribution.
4. Resolution: select only archive-root `<distribution>.dist-info/METADATA` for identity.
   Exactly one root distribution namespace is required. Nested vendored metadata remains
   ordinary payload under the root RECORD, with full hash, size, installed-byte and epoch checks.
   Non-directory UNIX ZIP attributes may contain permissions without a file-type bit;
   accept only type 0 or S_IFREG, never explicit symlink/special types. Directory checks stay
   exact. The only supported relocation root is `<normalized-name>-<version>.data`:
   `headers/<remainder>` maps to `prefix/include/python3.12/<library.name>/<remainder>`;
   `data/<remainder>` maps to `prefix/<remainder>`. Safe nonempty relative paths, exact root
   and role, no nested `.data`, and collision checks apply before installed reads.
   Direct URL supports only the canonical retained path's literal `as_uri()` spelling or
   that exact string with `%2B` replaced by `+`. Existing two archive-info shapes and exact
   hashes remain unchanged. No URI decoding, case/general normalization, host/query/fragment
   acceptance, alternate location or new permission follows from this compatibility.
   A missing or effectively empty `[gui_scripts]` section is metadata, not GUI execution.
   Any effective item, including inherited DEFAULT entries, remains forbidden. Duplicate/
   invalid ConfigParser metadata and existing console-target parsing remain unchanged.
5. Access patterns: one bounded ordered archive pass, keyed root/RECORD/member lookup and
   complete installed-member inventory; no package imports or archive extraction.
6. Structures: existing dictionaries, sets and immutable pins; no parallel parser or registry.
   Use one closed member-to-target mapping and reject duplicate mapped targets, ordinary/
   relocated and generated-addition collisions. Site-only namespace/installed-member output
   stays unchanged; full installed/archive-payload inventories include genuine relocations.
7. Complexity: O(archive members + payload bytes), with the existing central-directory,
   metadata, RECORD, expanded-size and per-member bounds preserved.
8. Concurrency: existing protected-file snapshots and before/after checks remain authoritative.
   The source fix does not turn a failed owner audit into an accepted runtime.
9. Dependency: only the existing stdlib wheel owner, focused source fixtures and this note;
   no new dependency or cross-layer import. Numeric proof schemas remain unchanged.
10. Failure/retry: reject missing/multiple/wrong root identity and nested payload corruption.
    Reject unsupported relocation role/root/traversal, missing/hash/extra/epoch drift, and
    every collision; root and installed RECORD set/value checks remain complete.
    Preserve both actual CPU failures and candidate/backup/phase/receipt history. No automatic
    publish retry, installed RECORD editing or metadata repair.
11. Alternative: forbidding vendored `.dist-info` rejects genuine setuptools83.0.0. Ignoring
    those files would lose closure. Distinguish root identity from fully verified nested payload.

Actual read-only CPU scan of the pinned successor input observed all56 packages successfully,
then verified33 and rejected23. The initial confirmed failure was setuptools83.0.0: one root
METADATA plus12 nested vendored METADATA, all12 matching exact hashes/sizes in its root RECORD.
Root classified 19 ZIP failures: their sole failed predicate was permission-only UNIX
`external_attr` (`create_system=3`, S_IFMT=0), not encryption/compression/size/ratio. Root
approved only the non-directory type correction with explicit special-type negatives.
Root also confirmed exact root-RECORD/hash members:
`greenlet-3.5.5.data/headers/greenlet.h` (4755B) and
`sympy-1.14.0.data/data/share/man/man1/isympy.1` (6659B), and approved only the two fixed
relocation mappings above. Actual protected installed RECORD/readback confirms the header
target is `include/python3.12/greenlet/greenlet.h`, not the initially guessed `include/site`
scheme; the latter remains a negative case. The man page is `share/man/man1/isympy.1`.
Root confirmed the one remaining direct-URL failure was parsed JSON equal to an existing
accepted hash/shape with only literal `+` in that exact retained archive path, and approved
only the two generated spellings above. Model/GPU/NEW execution count 0. No installed bytes
or metadata are repaired.

Source gates: focused wheel plus unchanged typed-distribution suites **274 PASS in 3.30s**;
shared eighteen-suite inventory **1290 PASS in 34.91s, skip 0**; explicit core Conda strict
mypy (`--follow-imports=silent --explicit-package-bases`) and API Conda Ruff/format passed
both changed Python files. The wheel suite retains the actual stdlib-only `-I -S -B`
import check. Root/vendored identity, root/nested RECORD/value/member closure, special types,
directory type, both relocation mappings, raw/mapped/generated collisions, wrong header
scheme, missing/hash/extra/epoch drift, both canonical plus spellings and existing archive
hash shapes are covered. Host/query/fragment/other path/double encoding/changed hash/extra
JSON fields remain negative cases.

Development failures were preserved: initial new fixtures used noncanonical synthetic
Base64/incorrect historical error labels; fixture values/expectations were corrected only.
The first shared gate exposed changed error ordering for empty `.data` roots and ordinary
file ancestors; original guard order/labels were retained without weakening checks. Its
new same-raw-path ancestor fixture consequently uses the historical error, while a distinct
mapped-parent collision fixture checks the new guard. A later existing alias rewrite case
did not establish observable epoch drift; temporary rewrite fixtures now set an explicit
mtime delta instead of depending on two writes straddling a clock tick. Production epoch
semantics are unchanged. The final gate above passed after those source/test corrections.

Only the authoritative wheel core, its focused test and this note changed. Prefix closure,
typed shim, schema, observer, proof/factory, audit leaf, installer and installed bytes stay
untouched. Root review/commit, explicit successor wheel/source assembly and actual owner
audit/publication remain required. This is neither installation/numeric admission nor an
actual CPU/GPU measurement, physical-lease migration or default activation.

## Confirmed empty GUI sections: subsequent same-owner correction

The first three-file revision was independently root-reviewed with raw hashes
`d1bd3fc5e5ef3f456161960e3e3edf216a5c653eaab83a117fa6dac58f299613` (core),
`ff938571238373edc797b030821b5d8cca3536b0efe85a9018df41aef9bf7e00` (test), and
`e2f3a8784d029876ca1b6285d881d2fbe6d3f7553bd7a9c0e946f7279dd08c47` (this note).
Root's independent nineteen-suite gate passed **1472 tests in 35.31s**, strict/style two
files PASS. The actual corrected-source CPU read-only scan then observed 56 packages and
verified 54 in 12.715s; only annotated-doc0.0.5 and typer0.27.1 failed GUI section presence.
These gate/failure facts remain historical; none is a numerical/runtime admission.

Targeted non-root read-only diagnosis used independently pinned input
`6ed5e50893fb88f1a88f42bb8ede14b382434fed662ab2a73a7cb24d4d6923b4`, retained root-owned
archive/installed files through `NumericalRuntimeFileSnapshots`, bounded ZIP construction,
exact archive raw pins and current member/ancestor/named/FD epochs. Its temp diagnostic
raw SHA was `32e1986ae02699b32477f9c7452973b2e9cc55ca978e9f8c6ac7627938fe2eb1`.
Both root RECORD sets and entry-point hashes/sizes, installed bytes and installed RECORD
rows matched exactly; no inspected package/model was imported or executed.

- annotated-doc0.0.5: archive 5302B, raw
  `117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101`; entry_points 34B,
  raw `e8e62005c2f21425207aa2e09ef332389c4f096ce0cbbb1ee2b2cf2ad3689ccb`.
- typer0.27.1: archive 122874B, raw
  `53150287edd11baeb4e4722c8e394fcdf8181c0ae89485cba8d25c778d5edd56`; entry_points 57B,
  raw `60ed770728aa59eb9ab3d5742400cb5004591547bf73053fef099336fc41610f`.

Both had exactly console_scripts/gui_scripts sections, **zero effective GUI entries and
zero defaults**; console counts were respectively 0/1. Root approved only effective-empty
compatibility in the same three files, not execution of real GUI entries. Tests cover
absent/empty/comment/whitespace section metadata bound to complete archive/installed
RECORD closure, plus actual/inherited GUI entries, duplicate/invalid sections/entries and
source/installed hash/epoch failures. Root must review this successor and rerun the actual
56 packages before any explicit successor assembly/publication; no blind retry occurs here.

Empty-GUI successor source gates: focused wheel/typed-distribution **287 PASS in 3.59s**;
same shared eighteen-suite inventory **1303 PASS in 35.26s, skip 0**; strict mypy/Ruff/format
two changed Python files PASS. Four absent/empty/comment/whitespace archive-associated
positives and nine effective/default/duplicate/invalid metadata negatives were added.
All existing layout/type/RECORD/byte/epoch/URI checks and historical behavior stay covered.
Only the same three source paths changed; no actual 56-package rerun, root/prefix/installed-byte,
model/GPU, DB, policy, helper, factory or proof mutation occurred in this correction.

Root reviewed both source revisions in full and matched each frozen three-path raw hash.
The final independent nineteen-suite inventory passed **1485 tests in36.47s, skip0**;
strict mypy/Ruff/format passed both Python files. Original helper/publisher/leaf/prefix-core
and numerical encoder/L2/f32 module bytes were not changed by this owning-verifier correction.

The final actual protected CPU read-only scan used input raw6ed5e508 and source core raw
`c7a1476a34a9800d2f0296b50f9a9f2fe96543ea2ea63cea67fbee748e9dc1b4`:
**observation56 PASS / verification56 PASS in12.878s**. Every wheel/member/RECORD/installed
hash and current epoch was checked; inspected packages/model were not imported or executed.
This is a wheel diagnostic, **not** complete Conda/source/ELF/host/prefix/runtime admission.
The second failed CPU candidate/backup/phase/empty receipt stays preserved and NEW remains
unexecuted. Its full successor assembly and owner audit must use a new explicit source/wheel
snapshot; this source result does not repair or relabel any failed runtime history.
