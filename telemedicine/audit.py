"""The append-only, tamper-evident audit log.

The README lists "Auditability: tamper-evident logs for access to records and
prescriptions" as a release gate, so the log is not a plain list of rows. Each
entry carries the hash of the entry before it, and each entry's own hash
covers its content and that link. Changing an entry therefore breaks every
hash after it, and :meth:`AuditLog.verify_chain` reports the break and where
it happened.

The log is append-only by construction: entries are frozen dataclasses and the
log exposes them as a tuple. There is no update or delete method, and a
``db/auth_schema.sql`` trigger rejects ``UPDATE`` and ``DELETE`` on the
corresponding table.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, Tuple

from telemedicine.errors import AuditError

GENESIS_HASH = "0" * 64

OUTCOME_SUCCESS = "success"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

VALID_OUTCOMES = frozenset({OUTCOME_SUCCESS, OUTCOME_DENIED, OUTCOME_ERROR})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_payload(payload: dict) -> str:
    """Hash an audit entry's payload.

    The hash covers every field of the entry plus the hash of the entry
    before it, so changing any field changes the hash.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    """One immutable audit entry."""

    sequence: int
    occurred_at: str
    # The account the action was performed by. It is None when the action
    # was not performed by an account at all — a system action, or a login
    # for an address that has no account — which is not the same as an id.
    actor_user_id: Optional[str]
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    detail: str
    previous_hash: str
    entry_hash: str

    def payload(self) -> dict:
        """The content that the entry hash covers."""
        return {
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "actor_user_id": self.actor_user_id,
            "actor_role": self.actor_role,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "outcome": self.outcome,
            "detail": self.detail,
            "previous_hash": self.previous_hash,
        }

    def compute_hash(self) -> str:
        return hash_payload(self.payload())


class AuditLog:
    """An append-only audit log with a hash chain."""

    def __init__(self, entries: Optional[Iterable[AuditEntry]] = None,
                 clock: Callable[[], datetime] = _utc_now):
        self._clock = clock
        self._entries: Tuple[AuditEntry, ...] = tuple(entries or ())

    # -- writing ----------------------------------------------------------

    def append(self, *, actor_user_id: Optional[str], actor_role: str, action: str,
               resource_type: str, resource_id: str, outcome: str = OUTCOME_SUCCESS,
               detail: str = "") -> AuditEntry:
        """Append an entry and return it.

        Raises :class:`~telemedicine.errors.AuditError` if the outcome is not
        one of the known values, or if the log's existing chain is broken —
        appending to a corrupted log would hide the corruption.
        """
        if outcome not in VALID_OUTCOMES:
            raise AuditError(f"unknown audit outcome '{outcome}'")
        if not self.verify_chain():
            raise AuditError("refusing to append to an audit log with a broken hash chain")
        previous_hash = self._entries[-1].entry_hash if self._entries else GENESIS_HASH
        sequence = self._entries[-1].sequence + 1 if self._entries else 1
        payload = {
            "sequence": sequence,
            "occurred_at": self._clock().astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"),
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome": outcome,
            "detail": detail,
            "previous_hash": previous_hash,
        }
        entry = AuditEntry(entry_hash=hash_payload(payload), **payload)
        self._entries = self._entries + (entry,)
        return entry

    # -- reading ----------------------------------------------------------

    @property
    def entries(self) -> Tuple[AuditEntry, ...]:
        """The entries, oldest first. The tuple is a snapshot; it cannot be mutated."""
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def entries_for_resource(self, resource_type: str, resource_id: str) -> Tuple[AuditEntry, ...]:
        return tuple(entry for entry in self._entries
                     if entry.resource_type == resource_type and entry.resource_id == resource_id)

    def entries_for_actor(self, actor_user_id: str) -> Tuple[AuditEntry, ...]:
        return tuple(entry for entry in self._entries if entry.actor_user_id == actor_user_id)

    def entries_for_outcome(self, outcome: str) -> Tuple[AuditEntry, ...]:
        return tuple(entry for entry in self._entries if entry.outcome == outcome)

    def head_hash(self) -> Optional[str]:
        """The hash of the last entry, or None when the log is empty.

        The head of the chain is what an anchor publishes, so that a chain
        rewritten afterwards can be told apart from an untouched one.
        """
        return self._entries[-1].entry_hash if self._entries else None

    # -- integrity --------------------------------------------------------

    def verify_chain(self) -> bool:
        """Return whether every entry hashes correctly and links to its predecessor."""
        return self.find_chain_break() is None

    def find_chain_break(self) -> Optional[int]:
        """Return the sequence number of the first broken entry, or ``None``.

        A break means either that an entry's own content does not match its
        hash, or that its ``previous_hash`` does not match the entry before
        it. Both indicate that the log was altered after the fact.
        """
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        for entry in self._entries:
            if entry.sequence != expected_sequence:
                return entry.sequence
            if entry.previous_hash != previous_hash:
                return entry.sequence
            if entry.compute_hash() != entry.entry_hash:
                return entry.sequence
            previous_hash = entry.entry_hash
            expected_sequence += 1
        return None
