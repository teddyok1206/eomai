"""Private local input receipts/results, never canonical transcript persistence.

No NAS or DB access. An exact immutable pending marker is created durably before
inference; a missing result never makes that claim executable a second time.
"""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import Self
from uuid import uuid4

from eom_identifiers import canonical_json_bytes
from eom_protocol.general_chat_grounding import ChatResultContract as ChatTurnResult
from eom_protocol.general_chat_grounding import (
    read_chat_result_document as read_chat_turn_result_document,
)
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerError,
    ChatWorkerFault,
    ChatWorkerOutput,
    ChatWorkerTicket,
    read_chat_worker_ticket,
    require_chat_ticket_result,
)

from eom_orchestrator.general_chat_socket import decode_chat_frame

TICKET_LIMIT = 4096
RESULT_LIMIT = 256000


class ChatLocalHandoff:
    def __init__(self, directory: Path, *, worker_uid: int) -> None:
        if not directory.is_absolute() or ".." in directory.parts:
            raise ChatWorkerFault(ChatWorkerError.INVALID)
        self.worker_uid = worker_uid
        try:
            self.directory = os.open(
                directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
        except OSError:
            raise ChatWorkerFault(ChatWorkerError.RECOVERY) from None
        node = os.fstat(self.directory)
        if node.st_uid != worker_uid or stat.S_IMODE(node.st_mode) != 0o700:
            os.close(self.directory)
            raise ChatWorkerFault(ChatWorkerError.INVALID)
        self.closed = False

    def _read(self, leaf: str, *, limit: int) -> bytes | None:
        if self.closed:
            raise ChatWorkerFault(ChatWorkerError.RECOVERY)
        try:
            descriptor = os.open(
                leaf,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=self.directory,
            )
        except FileNotFoundError:
            return None
        except OSError:
            raise ChatWorkerFault(ChatWorkerError.INVALID) from None
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != self.worker_uid
                or stat.S_IMODE(before.st_mode) != 0o400
                or not 0 < before.st_size <= limit
            ):
                raise ChatWorkerFault(ChatWorkerError.INVALID)
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(65536, limit + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ChatWorkerFault(ChatWorkerError.INVALID)
                chunks.append(chunk)
            after = os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ChatWorkerFault(ChatWorkerError.RECOVERY)
            if size != before.st_size:
                raise ChatWorkerFault(ChatWorkerError.RECOVERY)
            return b"".join(chunks)
        except OSError:
            raise ChatWorkerFault(ChatWorkerError.RECOVERY) from None
        finally:
            os.close(descriptor)

    @staticmethod
    def _leaves(ticket: ChatWorkerTicket) -> tuple[str, str]:
        read_chat_worker_ticket(ticket.model_dump(mode="json"))
        return ticket.claim_id + ".pending.json", ticket.claim_id + ".result.json"

    def lookup(self, ticket: ChatWorkerTicket) -> ChatWorkerOutput:
        pending_leaf, result_leaf = self._leaves(ticket)
        pending = self._read(pending_leaf, limit=TICKET_LIMIT)
        if pending is None:
            try:
                os.stat(result_leaf, dir_fd=self.directory, follow_symlinks=False)
            except FileNotFoundError:
                return ChatWorkerOutput(state="ABSENT", result=None)
            except OSError:
                raise ChatWorkerFault(ChatWorkerError.RECOVERY) from None
            raise ChatWorkerFault(ChatWorkerError.RECOVERY)
        try:
            recorded = read_chat_worker_ticket(decode_chat_frame(pending))
            if recorded != ticket:
                raise ChatWorkerFault(ChatWorkerError.INVALID)
            # Establish exact claim/hash/policy before materializing result bytes.
            result = self._read(result_leaf, limit=RESULT_LIMIT)
            if result is None:
                return ChatWorkerOutput(state="UNKNOWN", result=None)
            validated = read_chat_turn_result_document(decode_chat_frame(result))
            require_chat_ticket_result(ticket, validated)
            return ChatWorkerOutput(state="KNOWN", result=validated)
        except ChatWorkerFault:
            raise
        except Exception:
            raise ChatWorkerFault(ChatWorkerError.RECOVERY) from None

    def reserve(self, ticket: ChatWorkerTicket) -> bool:
        if self.closed:
            raise ChatWorkerFault(ChatWorkerError.RECOVERY)
        pending_leaf, _ = self._leaves(ticket)
        payload = canonical_json_bytes(ticket.model_dump(mode="json"))
        try:
            descriptor = os.open(
                pending_leaf,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.directory,
            )
        except FileExistsError:
            self.lookup(ticket)
            return False
        except OSError:
            raise ChatWorkerFault(ChatWorkerError.RECOVERY) from None
        try:
            self._write(descriptor, payload)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            os.fsync(self.directory)
        except OSError:
            # Retain even an uncertain/partial marker; never grant permission to
            # regenerate by deleting local evidence after a durability failure.
            raise ChatWorkerFault(ChatWorkerError.RECOVERY) from None
        finally:
            os.close(descriptor)
        return True

    @staticmethod
    def _write(descriptor: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("local handoff write incomplete")
            offset += count

    def publish(self, ticket: ChatWorkerTicket, result: ChatTurnResult) -> None:
        validated = read_chat_turn_result_document(result.model_dump(mode="json"))
        require_chat_ticket_result(ticket, validated)
        existing = self.lookup(ticket)
        if existing.state == "ABSENT":
            raise ChatWorkerFault(ChatWorkerError.RECOVERY)
        if existing.result is not None:
            if existing.result != validated:
                raise ChatWorkerFault(ChatWorkerError.INVALID)
            return
        _, result_leaf = self._leaves(ticket)
        payload = canonical_json_bytes(validated.model_dump(mode="json"))
        if len(payload) > RESULT_LIMIT:
            raise ChatWorkerFault(ChatWorkerError.INVALID)
        temporary = "staged-result-" + uuid4().hex
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.directory,
            )
            try:
                self._write(descriptor, payload)
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                # Link is atomic/no-replace; a competing final publication cannot
                # overwrite the first immutable result or expose partial bytes.
                os.link(
                    temporary,
                    result_leaf,
                    src_dir_fd=self.directory,
                    dst_dir_fd=self.directory,
                    follow_symlinks=False,
                )
            except FileExistsError:
                if self._read(result_leaf, limit=RESULT_LIMIT) != payload:
                    raise ChatWorkerFault(ChatWorkerError.INVALID) from None
            os.unlink(temporary, dir_fd=self.directory)
            os.fsync(self.directory)
        except OSError:
            raise ChatWorkerFault(ChatWorkerError.RECOVERY) from None
        finally:
            # This removes only our random temporary materialization, never a
            # pending identity, completed result, another process's file or NAS.
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=self.directory)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            os.close(self.directory)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
