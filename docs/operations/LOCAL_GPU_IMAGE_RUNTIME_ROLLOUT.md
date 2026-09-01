# Local GPU image runtime rollout

Status: reviewed operator procedure for the isolated SSD-1B runtime used by image-plan V6.

This rollout enables an optional SSD-1B semantic raster layer under the authoritative deterministic
SVG overlay. The local model is invoked only for `HYBRID_LOCAL_GENERATIVE`; a
`DETERMINISTIC_SVG` plan never constructs a provider request or consumes GPU capacity. It does not
expose the model to Codex workers and does not call an external API. Historical Content Pack 1.3
and 1.4 workflows retain their original release and route semantics.

## Immutable preflight

1. Require the reviewed Git commit and a clean worktree.
2. Require all source, package, boundary, and focused image tests to pass.
3. Confirm there is no active workflow lease or workflow command before restarting the workflow
   runner. A running textbook analysis job is a hard deployment stop; provider preparation may be
   staged, but runner restart and Content Pack activation wait.
4. Confirm `/srv/eom/models/image` contains the exact binding-pinned model revision and manifest.
5. Record the active generated Content Pack release and source/bundle/manifest hashes for rollback.
6. Confirm the shared non-secret configuration traversal root `/etc/eom` is a non-symlink
   `root:root:0755` directory. The image-runtime deployer must not take ownership of or narrow this
   shared boundary. Protected `/etc/eom/secrets` remains independently `root:eom:0750`, and each
   configuration or secret file retains its reviewed owner, group, and mode.
7. Confirm `/etc/eom/local-image-provider.json` is the reviewed non-secret binding projection at
   `root:root:0644`. The Application API and workflow runner may read this small immutable pointer
   contract so workflow creation can pin a provider/model revision. Both service sandboxes must
   deny `/srv/eom/models/image`, while Codex workers and the provider unit continue to deny
   `/etc/eom` entirely.

## Build and prepare runtime

Run the source-isolated offline wheel build as `eom`:

```bash
scripts/image_provider/build_release.sh
```

Record the two wheel paths and hashes. Run the reviewed runtime preparer as root with those exact
values and the exact source commit:

```bash
sudo -n scripts/image_provider/deploy_runtime.sh \
  <CONTRACT_WHEEL> <CONTRACT_SHA256> \
  <PROVIDER_WHEEL> <PROVIDER_SHA256> \
  <SOURCE_COMMIT>
```

The preparer creates only the `eom-image` no-login identity, installs the two local wheels with
`--no-deps`, normalizes only the manifest-listed model files, installs the fixed unit/polkit/binding,
and prepares `/srv/eom/image-workspaces`. It does not restart any service and does not activate a
Content Pack.

## Application deployment and activation gate

After the active-lease guard passes:

1. deploy the reviewed API/platform release through `scripts/api/deploy_release.sh`;
2. restart `eom-workflow-runner.service` once so it receives the `eom-image` supplementary group and
   new Catalog adapter;
3. verify the runner remains enabled/active and cannot read `/srv/eom/models/image`;
4. execute one disposable fixed-unit identity/composition smoke using a protected synthetic SVG
   overlay, never an Item workflow:

   ```bash
   sudo -n runuser -u eom-workflow-runner -g eom -G eom-image -- \
     /srv/eom/conda/envs/eom-api/bin/python -I \
     /home/eom/EOM/scripts/image_provider/run_fixed_composite_smoke.py
   ```

   The script deletes its exact workspace only after full receipt/hash validation. A failed smoke
   preserves its disposable state and provider workspace for diagnosis.
5. import, release, inspect, and activate `content/packs/generated-knowledge-item/1.5.0`;
6. verify new binding snapshots pin version 1.5, the binding SHA, model revision, and sampler while
   existing workflow rows retain their prior release pointers.

Do not activate 1.5 before the runner identity and fixed provider smoke pass. Never modify the
immutable 1.3 or 1.4 release in place. The fixed-unit smoke still exercises the historical V1
provider transport member name; production V6 publishes that byte-identical layer as the semantic
`generated-raster.png` artifact member.

## Acceptance

- provider unit runs as `eom-image:eom-image`, `PrivateNetwork=true`, with no NAS/DB/Codex access;
- runner starts only `eom-image-provider@imgreq_<32 hex>.service` and no arbitrary unit;
- model bytes are readable only by the provider identity;
- request workspace is `1730`, staged inputs `0440`, provider outputs `0640`, and world bits absent;
- a second GPU lease is denied rather than queued or retried implicitly;
- artifact primary member is the final 800x500 RGB PNG;
- the same Artifact Revision also pins canonical SVG overlay, generated semantic raster, and composite
  receipt; manifest and all SHA-256 values agree;
- no prompt or filesystem path is persisted in the artifact result;
- deterministic SVG workflows prove the provider adapter was not called, and HWPX native
  equation/table regressions remain green.

## Failure and rollback

There is no automatic provider retry and no fallback that changes a request's production route.
Preserve the workspace, unit journal, receipt if complete, and workflow failure evidence.

Rollback for new requests is pointer-based: activate the previously recorded Content Pack release,
restart the runner only if its unit is rolled back, and disable the provider unit. Do not delete the
model revision or artifacts referenced by history. Rollback does not touch the API database,
HWPX, textbook analysis, canonical Items, port 8000, or EOMIS.
