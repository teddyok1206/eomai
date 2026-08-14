# ADR 0004: PostgreSQL Deployment

Status: Accepted

## Context

The MVP needs a durable database and job queue without adding Redis or RabbitMQ. The host did not have PostgreSQL installed at audit time.

## Decision

- PostgreSQL is deployed with Docker Compose.
- The image is Docker Official Image `postgres:18-bookworm` pinned by digest.
- PostgreSQL binds only to `127.0.0.1:5432`.
- Primary data uses Docker named volume `eom_postgres_data` on local SSD.
- Secrets live outside Git in `/etc/eom/secrets/postgres.env`.
- Administrative role `eom_admin` is separated from application role `eom_app`.
- `eom_app` is non-superuser, cannot create databases or roles, and owns the `eom` database.
- Initial queue implementation uses PostgreSQL tables.
- Redis and RabbitMQ are not introduced in this phase.
- Backups are stored under `/mnt/nas/eom/backups/postgresql`.
- Restore dry-run is required after backup creation.

## Consequences

Operations must manage Docker and the secret file. Schema migrations can later run as `eom_app`.
