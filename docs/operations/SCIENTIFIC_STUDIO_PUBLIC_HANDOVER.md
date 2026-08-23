# Scientific Studio public handover

The canonical public route is `https://eomai.duckdns.org/studio/`. Caddy is the
only public listener and proxies the unchanged loopback GUI at
`127.0.0.1:8790`. Application API, observability, PostgreSQL, and the unrelated
historical port 8000 are never Caddy upstreams.

## Administrative boundary

Caddy's configuration API is a local control plane, not an application API.
The reviewed Caddyfile binds it to `/run/caddy-admin/admin.sock`. The systemd
drop-in creates `/run/caddy-admin` as `caddy:caddy:0700` and reloads through the
same socket. This prevents renderer and worker identities from reaching the
control plane through TCP loopback. Do not restore the default
`localhost:2019` listener.

## Public boundary

- Router TCP 80 and 443 forward only to `172.30.1.61:80` and `:443`.
- `/` redirects permanently to `/studio/`.
- `/studio/*` is forwarded without path stripping.
- HSTS is emitted only by the already HTTPS-only public hostname.
- Scientific Studio continues to use Secure, HttpOnly, SameSite cookies.

## Deployment and rollback

Run `sudo -n scripts/web_gui/install_public_handover.sh` from a reviewed, clean
`main` checkout. The installer validates the source configuration, records a
protected rollback copy, installs `root:root:0644` configuration, and restarts
Caddy once because the old TCP admin endpoint cannot reload itself into the new
socket contract safely. It then proves that TCP 2019 is closed, the caddy-only
socket works, a worker cannot reach it, reload uses the socket, and HTTPS emits
HSTS. Subsequent changes use `systemctl reload caddy`.

Rollback restores the prior Caddyfile and removes only the EOM drop-in, followed
by `systemctl daemon-reload` and one Caddy restart. It does not touch the GUI,
API, observability, PostgreSQL, HWPX, port 8000, or EOMIS.
