# ADR 0019: Separate Usage Plans from Usage Records

Status: Accepted

A plan is mutable intent within an explicit lifecycle; a record is immutable evidence that a
specific approved Item Revision appeared in a specific Deliverable Revision placement. Fulfillment
creates the record rather than converting the plan row into history. This preserves cancelled and
changed intent and makes actual use independently auditable.
