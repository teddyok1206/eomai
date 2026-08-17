# Usage Ledger Runbook

Create a placeholder deliverable, plan a placement, reserve it, and record actual use:

```bash
eomctl deliverable create --key placeholder-deliverable --type OTHER \
  --title PLACEHOLDER_CONTENT --edition 0.1 --actor-id operator_01
eomctl usage plan create --item-id <ITEM_ID> --deliverable-id <DELIVERABLE_ID> \
  --section PLACEHOLDER_SECTION --sequence 1 --actor-id operator_01
eomctl usage plan reserve <USAGE_PLAN_ID> --actor-id operator_01
eomctl usage record fulfill <USAGE_PLAN_ID> --actor-id operator_01 \
  --role PLACEHOLDER_ROLE
```

Plans express intent; records express immutable fact. Never update or delete a Usage Record.
Placement conflicts require a new sequence or deliverable revision. A failed pointer check must be
resolved by selecting an explicit approved Item Revision, not by changing history.
