# ADR 0027: Noninteractive Privileged Deployment

## Status

Accepted

## Decision

Retain the existing unprivileged release driver, but require `sudo -n true` before its install
phase and use only `sudo -n` for system-owned destinations and systemd. Builds, wheel inspection,
pip installation, Git inspection, and acceptance remain under `eom`. The script never calls
`sudo -v` and never waits for a password.

## Consequences

An interactive operator establishes a scoped sudo timestamp before invoking the install phase.
Automation fails closed when that authorization is absent. The installed deployment verifier is
root-owned before it is executed, and the source checkout is never built by root.
