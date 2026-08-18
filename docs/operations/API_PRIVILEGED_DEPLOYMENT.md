# Application API Privileged Deployment

Deployment has three ordered phases:

1. As `eom`, validate the clean release and run `scripts/api/deploy_release.sh --build-only`.
2. In a reviewed interactive operator shell, refresh sudo once and run the documented bootstrap and
   config installation commands with `sudo -n`. Then run `deploy_release.sh --install` as `eom`.
3. Drop the sudo timestamp and run unprivileged smoke, contract, authentication, and RBAC checks.

Codex and unattended automation do not acquire sudo credentials. `deploy_release.sh` performs a
noninteractive privilege preflight before any build or install side effect and every internal
privileged command uses `sudo -n`. Wheel build and pip installation always remain under `eom`.

The deployment installs a reviewed verifier at
`/usr/local/libexec/eom-api/verify-deployment-metadata` as `root:root:0755`, installs the unit,
verifies protected metadata, reloads systemd, enables and restarts the service, waits for health,
and records wheel hashes. A failed preflight changes nothing. A later failure stops the sequence;
inspect systemd and the recorded prior release rather than weakening file or sandbox permissions.

No phase changes UFW, `/etc/fstab`, ports 8000 or 8780, Observability, worker groups, Docker groups,
NAS, EOMIS, Git history, or a public network bind.
