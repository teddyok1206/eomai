# Manual Content Intake Operations

## Prerequisites

```bash
/srv/eom/conda/envs/eom-core/bin/alembic current
/srv/eom/conda/envs/eom-core/bin/eomctl content intake doctor
```

The NAS operational directories are `/mnt/nas/eom/content-intake/{inbox,accepted,rejected,
superseded,exports}`. They contain pointer manifests only; canonical bytes remain under the
artifact root.

## Run

1. Place received files in a new local source directory without modifying them.
2. Run `eomctl content intake create`.
3. Record the returned batch ID and compare source count and hashes.
4. Attach `analysis-report.md`, `mapping-proposal.yaml`, and `uncertainties.json`.
5. Run `eomctl content intake validate`.
6. Review uncertainties and record a human decision.
7. Inspect the event sequence and immutable artifact pointers.

Reject suspected secrets instead of deleting the source. Do not weaken the 500-file, 100 MiB per
file, or 2 GiB batch limits without a reviewed architecture change.
