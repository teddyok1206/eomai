# EOM Manual Content Intake Guide

## Who Sends What

Content leads continue to use their existing authoring tools. They do not need Git accounts,
branches, pull requests, YAML editing, or repository access. The operator receives the original
files through the approved internal transfer path. Supported intake metadata can describe HWPX,
DOCX, PDF, XLSX, CSV, Markdown, TXT, PNG, AI, JSON, YAML, Notion exports, and other internal files,
but V0 does not parse their domain content.

Keep the original filename. Never overwrite a received file. A correction is a new source batch
or source-file revision with a new hash. Record the sender using an internal reference rather than
personal data in filenames.

## Manual Analysis Handoff

The operator may attach files to ChatGPT manually. Do not attach secrets, credentials, student
data, private keys, or unrelated internal files. ChatGPT may return a structure summary, rule and
term candidates, conflicts, uncertainties, a mapping proposal, and a Codex handoff. The EOM server
does not call ChatGPT or any external LLM API.

ChatGPT output is untrusted external analysis. It must contain:

- `analysis-report.md` with every required section;
- `mapping-proposal.yaml` conforming to the V1 schema;
- `uncertainties.json` with explicit blocking flags.

Deterministic validation checks paths, hashes, schemas, references, unsafe fields, and blocking
uncertainties. A human decision is required before canonical content can be generated.

## Server Intake

Create a source-only directory and preserve its relative filenames. Register it with:

```bash
eomctl content intake create \
  --source-dir <PATH> \
  --batch-name PLACEHOLDER_BATCH \
  --received-by operator_01
```

Attach and validate the analysis:

```bash
eomctl content intake attach-analysis <BATCH_ID> \
  --analysis-report <PATH> \
  --mapping-proposal <PATH> \
  --uncertainties <PATH>

eomctl content intake validate <BATCH_ID>
```

The operator then records an explicit accept or reject decision. Acceptance does not trust or
execute the source documents. It only permits a validated proposal to become Content Pack source.
Real Integrated Science content is introduced only after operator approval.

## Storage and Git

Raw files, analyses, decisions, and large binaries are immutable NAS artifacts. Git stores EOM
code, schemas, compilers, placeholder fixtures, and approved canonical Content Pack source. Git is
an internal engineering history and is not a collaboration tool for content leads.
