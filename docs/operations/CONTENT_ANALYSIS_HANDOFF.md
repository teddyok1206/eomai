# Content Analysis Handoff

ChatGPT analysis is a manual external step. The operator uploads only approved source files and
receives three data files. The server never receives a conversation transcript and never contacts
ChatGPT automatically.

The Markdown report must contain the ordered headings listed in
`content/intake-templates/analysis-report.example.md`. The YAML proposal uses only data fields and
cannot contain command, shell, SQL, Python, import, external URL, or absolute path fields. JSON is
strict: duplicate keys, NaN, Infinity, and unknown fields fail validation.

Use `analysis_source_type: CHATGPT_MANUAL` when ChatGPT produced the proposal. This value is
provenance, not a trust score. A human must still accept or reject it.
