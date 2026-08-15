# ADR 0007: Development Progress Slack Reporting

Status: Accepted

## Context

Long-running Codex development work needs short milestone visibility without turning Slack into an
EOM control plane. Workflow commands, human approval, worker data, and runtime notifications have
different trust and durability requirements from development status updates.

## Decision

- Slack reporting is a development tool, not an EOM runtime feature.
- The reporter sends one-way HTTPS JSON requests through an Incoming Webhook.
- The destination channel is fixed when an operator creates the webhook.
- The webhook URL is a secret stored outside Git in `/etc/eom/secrets/dev-slack.env`.
- There are no inbound events, Socket Mode, Slack SDK, bot token, interactive component, or public
  Request URL.
- Slack reporting is unrelated to workflow approval and cannot create or change runtime state.
- Reporter failures are best-effort warnings and never stop development or runtime work. Only an
  explicitly requested `--strict` reporter invocation returns a delivery failure to its caller.
- Reports contain bounded Git metadata and short development summaries. They exclude full diffs,
  logs, worker inputs/results, domain content, credentials, database rows, and NAS paths.
- Redacted report JSON is archived locally under `/srv/eom/state/dev-reports` independently of
  delivery status.

## Consequences

Production packages must not import `eom_dev_reporter`. A missing webhook is operational activation
pending, not a code or workflow blocker. If production notification is later required, it needs a
separate ADR and branch with its own delivery, retry, privacy, and state semantics.
