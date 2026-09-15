# Preview and HWPX Acceptance — 2026-09-15

Observed at: 2026-09-15 12:51–12:58 UTC

This record covers the automated portions of roadmap steps S03 and S04 after the coordinated
`d4748d1` API/Web release. It uses the public HTTPS reverse-proxy path and immutable approved
products. It does not claim a human visual review in a browser or Hancom application.

## Public HTTPS and session boundary

The smoke used `https://eomai.duckdns.org`, the normal Scientific Studio login boundary, and an
Administrator session. It did not print the password, cookie, CSRF token, Item content, prompt, or
worker result. The session was logged out at the end.

Verified behavior:

- TLS and HSTS were present through the public reverse proxy;
- an unauthenticated recent-Item request and an unauthenticated Preview request returned 401;
- login returned the expected Administrator role and an opaque `Secure`, `HttpOnly`,
  `SameSite=strict` Studio cookie;
- session read, authenticated Studio shell, CSS, application JavaScript, Preview module, and Korean
  presentation vocabulary were available;
- logout invalidated the Web session;
- Web live/ready reported `LIVE`/`READY` with Application API and Observability active.

## Preview compatibility

The current recent-Item projection returned 20 bounded pointers. All 20 resolved to an available
`item-preview/3.0` projection with the `CONTENT_TEAM_V3` profile. Six declared image blocks were
fetched through the browser-facing media boundary; media type, length, ETag, declared SHA-256,
actual byte SHA-256, and `nosniff` matched.

Four additional current approved Item Revisions exercised the compatibility resolver:

| Stored Item content identity | Expected Preview profile | Result |
| --- | --- | --- |
| `eom.assessment.item-content/1.0` | `BLOCKS_V1` | PASS |
| `eom://schemas/item-registry/assessment-item-content-v1` | `BLOCKS_V1` | PASS |
| `eom.assessment.item-content/2.0` | `CONTENT_TEAM_V2` | PASS |
| `eom.assessment.item-content/3.0` | `CONTENT_TEAM_V3` | PASS |

The compatibility examples included two additional image responses with exact byte/hash identity.
This proves that the legacy URI alias is resolved without being reinterpreted as a new content
schema.

The focused browser/BFF suite covering login, stale response handling, request routing, Preview
projection, DOM renderer input, download/media routes, and frontend/backend alignment passed:
`76 passed`.

## Material and HWPX contract matrix

The HWPX source suite passed `184` tests, with one isolated privileged ownership test skipped by its
explicit opt-in gate. The suite covers native text/data/inquiry, one and two native tables, one and
two exact images, editable paired labels, table-to-image authored order, image-to-table authored
order, equation handling, Builder packaging, Manager independent acceptance, and negative byte or
label tampering. It preserves the key rules:

- a single table remains one editable native table with no image and no panel label;
- two tables remain two native tables with editable `(가)` and `(나)` text;
- one image is embedded once without a panel label;
- two images are embedded as two distinct PNG members with editable labels;
- mixed image/table material keeps authored order and does not invent paired labels.

The first HWPX invocation used the Builder-only environment for a cross-package suite and failed at
test collection because that runtime intentionally lacks Manager/platform packages. The second
invocation used the API environment but lacked Builder `lxml`. The accepted invocation explicitly
combined the API test environment with the installed Builder dependency path and the Builder source
root; the unchanged suite then passed. These were invocation-boundary failures, not product or
rendering failures.

## Existing immutable delivery compatibility

No new LLM, GPU, Item, Assembly, or HWPX build was created. Four existing successful single-Item
HWPX builds were queried and downloaded through the public authenticated Studio API. Their status
contracts were `SUCCEEDED`/`PASS`, and all declared output hashes matched 751,801 downloaded bytes in
total. Every file passed bounded ZIP CRC, HWPX mimetype, and core-document checks.

The current embedded-image 25-Item delivery was independently queried and downloaded:

| Field | Value |
| --- | --- |
| build | `hwpxbuild_da626008bbc14afc9d3408bc0107a0f9` |
| Item count | 25 |
| downloaded bytes | 258,476 |
| output SHA-256 | `sha256:5f1ab03c1123957c6bd550a9b2e9bfd73030fa40bbdcf70e6433d757e1f22bab` |
| status / validation | `SUCCEEDED` / `PASS` |
| ZIP CRC / mimetype / core | PASS |

A follow-up authenticated byte audit parsed every XML/HPF relationship in this exact downloaded
package. Every image manifest target resolved to an existing package-internal `BinData/` member,
every image was explicitly declared `isEmbeded=1`, every section binary reference resolved to a
declared image identity, and the image manifest set equalled the binary-member set. The package had
no URI scheme, network-relative path, absolute filesystem path, backslash path, root escape, or
missing relationship target. The downloaded SHA remained the exact committed SHA above. No new
delivery or generation was required for this confirmation.

This reuses the approved Item set and immutable build rather than consuming a new generation or
render budget solely for release alignment.

## Remaining human gate

The host has no installed supported browser engine, and automated HTTP/JavaScript contract tests do
not evaluate typography or visual layout. The following remain explicitly manual:

1. open Scientific Studio in a real browser and inspect at least one table-only, paired-image, and
   mixed-material Item;
2. switch quickly between two Items and visually confirm that the later selection remains visible;
3. open the exact whole-exam HWPX in Hancom and inspect editable tables, embedded images, `(가)/(나)`
   labels, equations, and page flow.

Until those observations are recorded:

`S03_AUTOMATED_PRODUCT_SMOKE=PASS`

`S04_AUTOMATED_DELIVERY_SMOKE=PASS`

`GATE_A=MANUAL_VISUAL_REVIEW_PENDING`
