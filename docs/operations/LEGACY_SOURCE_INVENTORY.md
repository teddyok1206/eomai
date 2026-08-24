# Legacy Source Inventory Operations

This runbook prepares a read-only legacy observation. It does not authorize a scan of a real root,
Content Intake, worker execution, knowledge analysis, or graph publication.

## Configuration boundary

Start from the repository examples:

- `config/legacy-source-inventory-policy.example.json` is a valid behavior example, not an
  assertion that its relative prefixes exist on a host;
- `config/legacy-source-roots.example.json` contains placeholder paths and must never be used as-is.

Review real relative prefixes without reading document content. Create the root mapping outside
Git, owned by the invoking operator or root and mode `0600`. The root path and configuration file
must have no symlink component. Never place credentials, DuckDNS data, Codex auth, DB URLs, or NAS
credentials in either document.

The configuration revision ID and per-root identity are immutable names for one reviewed mapping.
Changing an absolute root requires new values; never reuse an existing identity for another path.
Only those non-secret identities are hashed into the inventory—never the absolute path itself.

The policy may be repository-readable but must not be group/world writable. Its self-hash must be
recomputed with canonical JSON whenever a new immutable policy revision is intentionally created.
Do not edit a released policy in place.

## Separate dry-run gate

Use the explicit EOM API Conda environment. All arguments are absolute paths:

```bash
/srv/eom/conda/envs/eom-api/bin/eomctl knowledge legacy inventory dry-run \
  --root-alias EOMIS_LEGACY_SOURCE \
  --policy-file /absolute/reviewed/policy.json \
  --root-config-file /absolute/protected/legacy-source-roots.json \
  --manifest-file /absolute/protected/output/legacy-source-inventory.json
```

The output file is created with `O_EXCL` and mode `0600`. A pre-existing path, symlink component,
unsafe configuration mode, policy mismatch, capacity boundary, or tree mutation fails closed. The
command writes no source, DB, NAS, worker, or runtime state.

Validate and summarize an existing protected manifest without exposing paths or content:

```bash
/srv/eom/conda/envs/eom-api/bin/eomctl knowledge legacy inventory inspect \
  --manifest-file /absolute/protected/output/legacy-source-inventory.json
```

## Manifest-only Artifact commit

Commit is a later explicit operator action. It stores only the validated JSON inventory through the
existing Catalog/Orchestrator Artifact boundary; it does not ingest any observed file. Pin and type
the source-set hash shown by dry-run:

```bash
/srv/eom/conda/envs/eom-api/bin/eomctl knowledge legacy inventory commit \
  --manifest-file /absolute/protected/output/legacy-source-inventory.json \
  --confirm-source-set-sha256 sha256:<64-lowercase-hex>
```

Identical source sets converge through the source-set idempotency key. Do not run commit during the
initial real-root dry-run review.

## Safe reporting

Report only the closed root alias, inventory/source-set IDs and hashes, class counts/bytes, and
stable error code. Never report absolute paths, relative filenames, file contents, manifests,
credentials, or source excerpts to Slack.
