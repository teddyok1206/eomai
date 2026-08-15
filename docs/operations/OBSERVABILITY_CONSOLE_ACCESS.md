# Observability Console Access

Create an SSH tunnel without changing firewall or router rules:

```bash
ssh -N -L 8780:127.0.0.1:8780 eom@<SERVER>
```

Open:

```text
http://127.0.0.1:8780/observe/
```

Read the initial token locally from `/home/eom/.eom-observe-initial-token`. Do not paste it into a
shell command, ticket, Slack message, or log. Delete the one-time file after login is confirmed.

The console is read-only. Node selection, filters, pause/resume, and detail views change browser state
only. Workflow approval, rework, cancellation, retry, worker control, shell, and SQL actions are not
available.

Rotate access without printing the new token:

```bash
/srv/eom/conda/envs/eom-observe/bin/eom-observe auth rotate-token
systemctl restart eom-observe.service
```

The command writes the replacement token to the same 0600 one-time file. Existing signed sessions
remain valid until their configured expiry; rotate the session secret for immediate invalidation.
