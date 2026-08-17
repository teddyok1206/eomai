# Content Pack Release

Import validates source, Intake provenance, profiles, templates, canonical hashes, and bundle
round-trip before creating a `VALIDATED` release.

```bash
eomctl content pack import /srv/eom/staging/catalog/pack-source-0.1.0
eomctl content pack release <PACK_RELEASE_ID> --actor-id admin_01
eomctl content pack activate <PACK_RELEASE_ID> \
  --environment development --actor-id admin_01
eomctl content pack resolve --pack-key generic-placeholder --environment development
```

Re-import of the same key, version, and hash returns the existing release. A different hash for the
same key/version is rejected. Never edit a released bundle or its database row. Create a new semantic
version, validate it, and activate the new release. Existing workflows remain pinned to the previous
release.

Rollback changes only the active pointer to a still-eligible released revision. It never mutates or
deletes release history.
