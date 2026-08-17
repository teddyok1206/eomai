# Content Pack Authoring

Content Pack source contains text data only (`.yaml`, `.yml`, `.json`, `.md`, `.txt`). Do not add
binary files, secrets, executable files, external fetch instructions, Python, shell, or SQL.

Generate a source tree from an accepted Intake:

```bash
eomctl content intake generate-pack-source <BATCH_ID> \
  --pack-key generic-placeholder \
  --new-version 0.1.0 \
  --output /srv/eom/staging/catalog/pack-source-0.1.0
```

Validate and build twice when deterministic output is under review:

```bash
eomctl content pack validate /srv/eom/staging/catalog/pack-source-0.1.0
eomctl content pack build /srv/eom/staging/catalog/pack-source-0.1.0 \
  --output /srv/eom/staging/catalog/pack-build-0.1.0
```

Prompt templates accept only declared `{{ dotted.path }}` scalar variables. Conditions, loops,
functions, filters, includes, environment variables, and dynamic lookup are rejected.
