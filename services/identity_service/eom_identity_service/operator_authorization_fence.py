"""Required Identity-owner transaction fence; no implementation or grant is activated."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session


class OperatorAuthorizationFence(Protocol):
    """Official Identity owner must implement this before registry composition.

    The caller identity is authenticated owner context, never request/model role
    data. Bind the exact Session and active root transaction; cooperate with all
    supported role revocation, disable/delete and required-password-change writers.
    Re-read/refresh current operator state before returning and retain the fence
    through root commit/rollback. No boolean approval or transferable grant is
    returned. Catalog must still query actual current permissions/roles and policy.

    A missing implementation is unavailable. This interface neither grants IAM
    UPDATE to Catalog nor claims its current runtime can take an Operator row lock.
    """

    def fence_current_operator(self, session: Session, operator_id: str) -> None: ...
