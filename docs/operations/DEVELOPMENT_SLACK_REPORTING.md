# Development Slack Reporting

## Boundary

`eom_dev_reporter` publishes short Codex development milestones through a Slack Incoming Webhook.
It cannot start, approve, rework, cancel, or inspect an EOM workflow. It does not use PostgreSQL,
NAS, Docker, Codex authentication, or worker HOME directories. Delivery failure is best-effort and
does not affect development tests or runtime state.

## 1. Create The Slack App

Create an internal Slack app in the intended workspace using the Slack administration UI. Do not
enable Socket Mode, event subscriptions, interactive components, slash commands, shortcuts, or bot
scopes.

## 2. Enable Incoming Webhooks

Enable only Incoming Webhooks for the app.

## 3. Select The Channel

Choose the development-status channel while creating the webhook. The webhook fixes the channel;
the reporter does not accept a channel override.

## 4. Obtain The Webhook URL

Copy the generated URL directly into the protected secret file in the next step. Do not place it in
Git, a command argument, shell history, an issue, or a chat message.

## 5. Create The Secret File

Create an empty protected file, then edit it with a privileged editor:

```bash
sudo install -o eom -g eom -m 0640 /dev/null /etc/eom/secrets/dev-slack.env
sudoedit /etc/eom/secrets/dev-slack.env
```

The file accepts only these keys:

```text
EOM_DEV_SLACK_REPORTING_ENABLED=true
EOM_DEV_SLACK_WEBHOOK_URL=<secret Incoming Webhook URL>
```

Do not print or source this file in an interactive shell.

## 6. Verify Permissions

```bash
sudo chown eom:eom /etc/eom/secrets/dev-slack.env
sudo chmod 0640 /etc/eom/secrets/dev-slack.env
```

## 7. Run Doctor

```bash
/srv/eom/conda/envs/eom-core/bin/python -m eom_dev_reporter doctor
```

Doctor reports file presence, permissions, enabled/configured flags, masked webhook status, Git
metadata access, and DNS resolution. It never prints the URL.

## 8. Dry Run

```bash
/srv/eom/conda/envs/eom-core/bin/python -m eom_dev_reporter send \
  --dry-run \
  --status TESTING \
  --phase reporter-validation \
  --summary "EOM development reporter dry run" \
  --test "unit=PASS"
```

The command validates and archives a redacted report and prints the redacted Slack payload without
opening a network connection.

## 9. Live Test

The optional live test is marked `dev_slack_live` and must be invoked explicitly only after doctor
reports operational readiness. Human confirmation in the selected channel remains a manual
acceptance step.

## 10. Send A Milestone

```bash
/srv/eom/conda/envs/eom-core/bin/python -m eom_dev_reporter send \
  --status IN_PROGRESS \
  --phase workflow-definition \
  --summary "Domain-neutral workflow definition implementation" \
  --completed "Baseline tests PASS" \
  --next "PostgreSQL migration" \
  --test "unit=PASS"
```

Use `STARTED`, `IN_PROGRESS`, `TESTING`, `BLOCKED`, and `COMPLETED` only at meaningful milestones.

## 11. Rotate The Secret

Create a replacement webhook in Slack, update the protected file through `sudoedit`, run doctor and
a live test, then revoke the old webhook. Never retain the old URL in backups or reports.

## 12. Revoke Reporting

Disable or delete the Incoming Webhook in Slack and set the enabled flag to `false`. Remove the
secret file only after confirming it is no longer needed.

## 13. Troubleshooting

Stable delivery states distinguish missing configuration, disabled reporting, DNS failure, timeout,
HTTP failure, invalid response, and invalid payload. The default command exits successfully after a
delivery warning; `--strict` makes delivery failure return nonzero. Neither behavior changes an EOM
workflow.

## 14. Operation Without Slack

When the secret is absent, reporter code, unit tests, dry-run, and local archive remain available.
Record the situation as `Development Slack incoming webhook configuration` under operational
activation pending, not as a code blocker.

## 15. Codex Reporting Command

Codex development sessions use `scripts/dev/report-progress` with the same arguments. Reports must
remain short and must never include secrets, complete logs, complete diffs, worker data, domain
content, database records, or full NAS paths.
