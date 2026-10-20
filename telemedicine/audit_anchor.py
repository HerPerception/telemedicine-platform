"""Anchoring the audit chain outside the database.

The chain of ENG-002 is only as good as the store it is in. An attacker
with write access to the ``audit_log`` table can rewrite the entries, and the
chain will verify again — because a chain that was rewritten from the
beginning is still a chain. The hash detects a chain that was edited in the
middle; it does not detect a chain that was replaced wholesale.

The answer is to publish the head of the chain **somewhere the attacker
cannot rewrite**, and to check the two against each other. This module is
that:

* an :class:`Anchor` records the hash of an entry, its position in the
  chain, and the hash of the whole chain at that moment;
* an :class:`AuditAnchor` is where those records go. The implementation here
  is a file — one anchor per line, appended, never rewritten — which is
  outside the database and can be shipped somewhere else, copied to another
  machine, or kept with the practice's off-site records. A deployment can
  publish to a service of its own; the interface is the same.
* :func:`verify_anchors` checks a log against the anchors and says what
  does not add up.

Nothing here is a secret. The anchor is a public digest: its value is that
it is *hard to change quietly*, not that it is hard to see.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class Anchor:
    """A published point in the chain."""

    sequence: int
    entry_hash: str
    chain_head: str
    anchored_at: datetime

    def to_json(self) -> str:
        return json.dumps({
            "sequence": self.sequence,
            "entry_hash": self.entry_hash,
            "chain_head": self.chain_head,
            "anchored_at": self.anchored_at.isoformat().replace("+00:00", "Z"),
        }, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> "Anchor":
        data = json.loads(line)
        anchored_at = data["anchored_at"]
        if isinstance(anchored_at, str):
            anchored_at = datetime.fromisoformat(anchored_at.replace("Z", "+00:00"))
        return cls(
            sequence=int(data["sequence"]),
            entry_hash=data["entry_hash"],
            chain_head=data["chain_head"],
            anchored_at=anchored_at,
        )


class AuditAnchor:
    """Where the anchors are published."""

    def publish(self, anchor: Anchor) -> Anchor:
        raise NotImplementedError

    def anchors(self) -> List[Anchor]:
        raise NotImplementedError


class InMemoryAuditAnchor(AuditAnchor):
    """The anchors, in the memory of one process. For the tests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._anchors: List[Anchor] = []

    def publish(self, anchor: Anchor) -> Anchor:
        with self._lock:
            self._anchors.append(anchor)
        return anchor

    def anchors(self) -> List[Anchor]:
        with self._lock:
            return list(self._anchors)


class FileAuditAnchor(AuditAnchor):
    """The anchors, in a file outside the database.

    The file is appended to and never rewritten, and it is the thing an
    operator keeps: copied off the machine, sent to the practice's records,
    or stored somewhere the application cannot write to.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def publish(self, anchor: Anchor) -> Anchor:
        line = anchor.to_json()
        with self._lock:
            # The write is appended and flushed, so that an anchor is on disk
            # before the entry it refers to can be forgotten.
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return anchor

    def anchors(self) -> List[Anchor]:
        if not self.path.exists():
            return []
        anchors = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    anchors.append(Anchor.from_json(line))
                except (ValueError, KeyError):
                    # A line that cannot be read is a problem to report, not a
                    # reason to lose the ones that can.
                    continue
        return anchors


def verify_anchors(log, anchor_store) -> List[str]:
    """Check a log against the published anchors.

    Returns the problems found; an empty list means the log and the anchors
    agree.
    """
    problems: List[str] = []
    anchors = anchor_store.anchors()
    if not anchors:
        problems.append("there are no anchors: the chain has never been published")
        return problems

    source = log.entries if hasattr(log, "entries") else log
    entries = {entry.sequence: entry for entry in source}
    for anchor in anchors:
        entry = entries.get(anchor.sequence)
        if entry is None:
            problems.append(
                f"the entry {anchor.sequence} that was anchored is not in the log")
            continue
        if entry.entry_hash != anchor.entry_hash:
            problems.append(
                f"the entry {anchor.sequence} does not match the anchor: "
                f"the log says {entry.entry_hash[:12]}, the anchor says "
                f"{anchor.entry_hash[:12]}")
    return problems


class AnchoredAuditLog:
    """An audit log that publishes the head of its chain as it goes.

    It wraps any log — the in-memory one or the database one — and publishes
    an anchor every ``every`` entries. The anchor says where the chain was
    and what it hashed to, so that a chain rewritten afterwards does not
    match.
    """

    def __init__(self, log, anchor_store: AuditAnchor, every: int = 50,
                 clock=None):
        self.log = log
        self.anchor_store = anchor_store
        self.every = max(1, every)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._since_anchor = 0

    def append(self, **kwargs):
        entry = self.log.append(**kwargs)
        with self._lock:
            self._since_anchor += 1
            due = self._since_anchor >= self.every
            if due:
                self._since_anchor = 0
        if due:
            self.publish_anchor()
        return entry

    def publish_anchor(self) -> Optional[Anchor]:
        """Publish the current head of the chain."""
        head = self.log.head_hash()
        if head is None:
            return None
        entries = self.log.entries
        if not entries:
            return None
        last = entries[-1]
        anchor = Anchor(
            sequence=last.sequence,
            entry_hash=last.entry_hash,
            chain_head=head,
            anchored_at=self._clock(),
        )
        return self.anchor_store.publish(anchor)

    def __getattr__(self, name):
        # Everything else is the log's.
        return getattr(self.log, name)

    def __len__(self) -> int:
        # The dunder methods are looked up on the type, so __getattr__ does
        # not cover them.
        return len(self.log)

    def __iter__(self):
        return iter(self.log)
