#!/srv/eom/conda/envs/eom-api/bin/python -I
"""Fail closed when a runtime deployment would interrupt claimed worker work."""

from __future__ import annotations

from eom_orchestrator.control_models import WorkerLeaseRecord
from eom_orchestrator.database import build_engine, build_session_factory
from sqlalchemy import func, select


def main() -> int:
    engine = build_engine()
    sessions = build_session_factory(engine)
    try:
        with sessions() as session:
            active_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkerLeaseRecord)
                    .where(WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")))
                )
                or 0
            )
    finally:
        engine.dispose()
    if active_count:
        print(f"ACTIVE_WORKER_LEASES={active_count}")
        return 20
    print("ACTIVE_WORKER_LEASES=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
