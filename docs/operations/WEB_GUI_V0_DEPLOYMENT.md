# EOM Web GUI V0 deployment contract

## Current ownership and ports

The listener on `0.0.0.0:8000` is a manual `uvicorn` process with working directory
`/home/eom/linux_server_bundle`. It is not owned by `/home/eom/EOM`; Web GUI deployment must not
stop, replace, or modify it. Application API remains on `127.0.0.1:8765` and Observability remains
on `127.0.0.1:8780`.

Scientific Studio uses `127.0.0.1:8790`. Public/LAN exposure requires a separately reviewed reverse
proxy handover; it is not achieved by changing the bind to `0.0.0.0` or taking port 8000.

## Runtime contract

- service: `eom-web-gui.service`;
- user/group: dedicated `eom-web:eom-web`, with no sudo, Docker, worker, or `eom` group membership;
- environment: `/srv/eom/conda/envs/eom-web`, installed non-editably from the reviewed wheel;
- configuration: `/etc/eom/web-gui.yaml`, root-owned and read-only to the service;
- secret environment: `/etc/eom/secrets/web-gui.env`, root:`eom-web` mode `0640`;
- working directory: `/var/lib/eom-web`, `eom-web:eom-web` mode `0700`;
- health: `/studio/api/v1/health/live` and `/studio/api/v1/health/ready`;
- upstreams: loopback Application API and Observability only;
- session storage: bounded in-process storage, so V0 runs exactly one worker.
- HWPX capability: read live from Application API; it is not duplicated in GUI configuration.
- graceful shutdown: Uvicorn cancels lingering requests after 10 seconds, before systemd's
  15-second stop boundary. This bounds active SSE connections without weakening the service sandbox.

The only Web GUI secret is the existing Observability access token made available as
`EOM_WEB_OBSERVE_ACCESS_TOKEN`. Application API credentials are entered by the operator and API
access/refresh tokens remain in server memory. No secret is stored in browser local storage.

## Dependency rationale

FastAPI/Uvicorn provide the existing EOM HTTP/runtime conventions, Pydantic validates the BFF
contracts, HTTPX implements the loopback adapters, PyYAML loads strict operator configuration, and
Typer provides the established CLI style. There is no Jinja, React, Vue, Node runtime, remote font,
icon CDN, or browser database driver dependency.

## Handover and rollback

Deployment starts the new loopback service without touching port 8000. Verify login, CSP, API
health, read-only Explorer behavior, and the Application API-backed HWPX capability locally before
adding a reviewed reverse-proxy route. Rollback removes that route first, stops/disables only
`eom-web-gui.service`, and reinstalls the prior recorded wheel and unit. It never changes
Application API, Observability, EOMIS, workers, checkpoints, or canonical workflow data.
