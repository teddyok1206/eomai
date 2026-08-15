# Agent Rules

These rules apply to all future Codex and automation work in `/home/eom/EOM`.

1. Never modify `/home/eom/EOMIS`.
2. Treat `/home/eom/EOM` as a separate Git repository with separate history.
3. Use protocol-first development. Define JSON Schema before worker behavior.
4. Validate agent messages with JSON Schema 2020-12 and future Pydantic models.
5. Do not let workers communicate directly with each other.
6. Route all worker work through the orchestrator.
7. Do not let workers write to NAS. Workers read staged local inputs and submit local results.
8. Only the orchestrator commits validated artifacts to NAS.
9. Never commit secrets, tokens, credentials, `.env` files, Codex auth, SSH keys, or database passwords.
10. Preserve logical ID, revision ID, and SHA-256 content hash as separate immutable concepts.
11. Treat every external file as untrusted input.
12. Use explicit Conda environments. Do not rely on an ambient Python.
13. Apply formatter, linter, type checker, and focused tests before merging core code.
14. Do not merge core protocol, storage, state-machine, or worker changes without tests.
15. Document the reason for every new dependency.
16. Use UTC for system timestamps.
17. Use Asia/Seoul only for user-facing display.
18. Do not put generated artifacts directly into Git.
19. Store HWPX, PNG, AI, PDF, long logs, and backups in NAS with manifests.
20. Do not use port 8000 for new EOM services. The reserved API bind is `127.0.0.1:8765`.
21. Do not use external LLM APIs.
22. Do not copy root Codex auth to workers.
23. Do not add worker users to sudo, Docker, or the `eom` group.

## Development Progress Reporting

- When the development reporter is enabled, send reports only at important milestones.
- The Slack development reporter is not a production runtime feature.
- Slack failure must not block development, tests, commits, or runtime workflows.
- Never send secrets, full diffs, full logs, worker prompts or results, or item content to Slack.
- Keep routine reporting milestone-based and avoid excessive messages.
- Report `BLOCKED` and `COMPLETED` milestones immediately.
