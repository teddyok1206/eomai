# Customer Support Manual Verification Checklist

Status: deferred until the reviewed source candidate is deployed and its automated live canary has
passed. This checklist does not authorize deployment, Codex execution, or state mutation.

The user asked to receive visual checks once, at the end, rather than being interrupted during
implementation. Automated contract, authorization, idempotency, database, and Artifact checks stay
separate from these observations.

## Scientific Studio

- [ ] Open **고객센터** from the normal authenticated navigation on a desktop-width browser.
- [ ] Confirm the category, subject, question, optional error-code field, and submit button are
  readable without explanatory clutter.
- [ ] Submit the agreed harmless HOW_TO canary only once and confirm it appears in **내 문의**.
- [ ] Confirm `접수됨` → `Codex 확인 중` → `답변 완료` is understandable and refreshes without
  replacing the currently selected case with a late response from another case.
- [ ] Confirm Korean answer paragraphs and recommended actions wrap cleanly and no HTML supplied by
  the worker is interpreted.
- [ ] Confirm normal users see friendly subjects and states, not Workflow, Job, Artifact, revision,
  capacity, hash, or internal path values.
- [ ] If the answer requires operator help, confirm the user sees only the safe escalation notice
  and never the operator-only summary.
- [ ] If more than one page exists, use **이전 문의 더 보기** and confirm rows do not duplicate.
- [ ] Repeat the layout check at a narrow/mobile width.

## Expected product limit

- [ ] Confirm the UI states that a total Web/API/login outage requires the external operator
  channel; the in-product customer center is not presented as an emergency out-of-band channel.

Record the UTC observation time, browser, deployed Web/API source identities, canary Workflow ID,
and PASS/FAIL without copying the question, answer, prompt, result, token, cookie, or full log into
the evidence record or Slack.
