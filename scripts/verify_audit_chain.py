#!/usr/bin/env python3
"""Check the audit chain against the published anchors.

Usage:
    python3 scripts/verify_audit_chain.py <dsn> <anchor-file>

The chain of the audit log is checked twice:

1. **internally** — every entry hashes correctly and links to the entry
   before it. That detects an entry that was edited in the middle.
2. **against the anchors** — the digests published outside the database are
   compared with the entries they name. That detects a chain that was
   rewritten from the beginning, which the internal check cannot see.

Exit status is 0 when everything agrees, and 1 when it does not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.audit_anchor import (  # noqa: E402
    FileAuditAnchor,
    verify_anchors,
)
from telemedicine.persistence.audit_store import PostgresAuditLog  # noqa: E402
from telemedicine.persistence.database import Database  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dsn", help="the PostgreSQL connection string")
    parser.add_argument("anchors", help="the file the anchors were published to")
    args = parser.parse_args(argv)

    try:
        log = PostgresAuditLog(Database(args.dsn))
        anchors = FileAuditAnchor(args.anchors)
    except Exception as error:
        print(f"the chain could not be checked: {error}", file=sys.stderr)
        return 1

    break_point = log.find_chain_break()
    if break_point is not None:
        print(f"the chain is broken at entry {break_point}", file=sys.stderr)
    else:
        print("the chain is intact")

    problems = verify_anchors(log, anchors)
    if problems:
        print("the chain and the anchors do not agree:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"the chain matches {len(anchors.anchors())} anchor(s)")
    return 0 if break_point is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
