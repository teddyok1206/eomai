# ADR 0020: Catalog Application Boundary

Status: Accepted

CLI, future HTTP, GUI, Excel, and HWPX adapters call typed catalog commands and queries. They do
not access catalog tables directly. Application services own validation, idempotency,
transactions, and pointer resolution; domain models own state tables; infrastructure implements
database and artifact ports. No HTTP API or port allocation is introduced in V0.
