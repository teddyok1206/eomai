# Manual Hancom Validation

Linux validation cannot establish Hancom rendering compatibility. Perform this procedure on the
laboratory Windows PC with the recorded Hancom Office Hangul version.

## Open

1. Start the gate with `eomctl hwpx manual-validation start <BUILD_ID>`.
2. Open the exact generated HWPX. Record any repair, recovery, font substitution, or error dialog.
3. Confirm placeholder item number, both stems, the 2-by-3 table, PNG, equation, three statements,
   five choices, points, answer, intent, overview, and three explanations.
4. Record page count and layout anomalies. A screenshot is permitted only for this placeholder
   document and must not enter Git.

## Edit And Save

1. Change one placeholder text value and save under a new `.hwpx` name.
2. Close Hancom, reopen the re-saved file, and confirm the edit remains.
3. Put the re-saved file in `/mnt/nas/eom/hwpx/poc-v0/manual-validation/inbox/`.
4. Complete the gate:

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx manual-validation complete <BUILD_ID> \
  --hancom-version '<EXACT_VERSION>' \
  --windows-version '<EXACT_VERSION>' \
  --open-result pass \
  --save-result pass \
  --resaved-file <PATH> \
  --performed-by '<ACTOR_ID>' \
  --notes '<SANITIZED_NOTES>'
```

The command imports the re-saved file through the secure parser, records a separate immutable
artifact revision, and compares canonical semantics and package structure. Do not include a real
person's Windows account name or document content in notes.

Only `MANUAL_HANCOM_OPEN`, `MANUAL_HANCOM_SAVE`, and `RESAVED_SEMANTIC_COMPARE` PASS records can
advance the completion claim to `HWPX_POC_V0_COMPLETE`.
