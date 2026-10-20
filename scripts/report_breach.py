#!/usr/bin/env python3
"""Report a personal data breach.

Usage:
    python3 scripts/report_breach.py <dsn> --since 2026-10-21T09:00:00Z [--until ...]
                            [--nature "..."] [--records patient-1,patient-2]

Section 40(2) of the Nigeria Data Protection Act 2023 says that a data
controller must, **within 72 hours** of becoming aware of a breach which is
likely to result in a risk to the rights and freedoms of individuals, notify
the Commission of the breach, and where feasible describe the nature of it
"including the categories and approximate numbers of data subjects and
personal data records concerned".

This script assembles what can be assembled from the facts the system
holds — the accounts whose records were touched, and how many records and
access events there were — and leaves the parts that are judgments to the
person who writes the report:

* the **likely consequences** of the breach;
* the **measures taken or proposed** to address it.

It says so on the face of the report, because a report that looks finished
when it is not is worse than one that admits what is missing.

This is a drafting aid, not a notification. The notification to the
Commission goes through the NDPC's own channel, and the decision to notify
is the controller's.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.persistence.audit_store import PostgresAuditLog  # noqa: E402
from telemedicine.persistence.database import Database  # noqa: E402


def parse_moment(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def moment(value) -> datetime:
    """The instant of an audit entry, whichever way it is written.

    The audit log keeps its instants as ISO 8601 text — that is what the
    hash chain is computed over — so a report window has to be compared in
    the same terms.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_report(log, since: datetime, until: datetime, nature: str,
                  records: list) -> str:
    """The report, as text."""
    entries = [entry for entry in log.entries
               if since <= moment(entry.occurred_at) <= until]

    data_subjects = sorted({entry.actor_user_id for entry in entries
                            if entry.actor_user_id})
    record_ids = sorted({entry.resource_id for entry in entries if entry.resource_id})
    by_action = {}
    for entry in entries:
        by_action[entry.action] = by_action.get(entry.action, 0) + 1

    lines = [
        "PERSONAL DATA BREACH — DRAFT REPORT",
        "Nigeria Data Protection Act 2023, section 40(2)",
        "",
        f"Window: {since.isoformat()} to {until.isoformat()}",
        f"Access events in the window: {len(entries)}",
        "",
        "NATURE OF THE BREACH",
        f"  {nature}",
        "",
        "CATEGORIES AND APPROXIMATE NUMBERS CONCERNED",
        f"  Data subjects (accounts with records touched): {len(data_subjects)}",
        f"  Personal data records concerned: {len(record_ids)}",
        "",
    ]
    if data_subjects:
        lines.append("  The accounts concerned:")
        for subject in data_subjects:
            lines.append(f"    - {subject}")
        lines.append("")
    if record_ids:
        lines.append("  The records concerned:")
        for record in record_ids:
            lines.append(f"    - {record}")
        lines.append("")
    if by_action:
        lines.append("  What was done with them:")
        for action, count in sorted(by_action.items()):
            lines.append(f"    - {action}: {count}")
        lines.append("")
    if records:
        lines.append("  Records the controller believes were affected:")
        for record in records:
            lines.append(f"    - {record}")
        lines.append("")

    lines += [
        "TO BE COMPLETED BY THE CONTROLLER",
        "  Likely consequences of the breach:",
        "  Measures taken or proposed to address it:",
        "  Whether the data subjects have been informed, and when:",
        "",
        "  A breach likely to result in a HIGH risk to the rights and freedoms of a",
        "  data subject must be communicated to that data subject immediately, in",
        "  plain and clear language (section 40(3)).",
        "",
        "  This is a drafting aid. The notification itself goes to the Commission",
        "  through the NDPC's own channel, within 72 hours of becoming aware of the",
        "  breach.",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dsn", help="the PostgreSQL connection string")
    parser.add_argument("--since", required=True, help="the start of the window")
    parser.add_argument("--until", default=None,
                        help="the end of the window (default: now)")
    parser.add_argument("--nature", default="to be described",
                        help="what happened, in plain words")
    parser.add_argument("--records", default="",
                        help="a comma-separated list of records believed affected")
    args = parser.parse_args(argv)

    since = parse_moment(args.since)
    until = parse_moment(args.until) if args.until else datetime.now(timezone.utc)
    records = [item.strip() for item in args.records.split(",") if item.strip()]

    try:
        log = PostgresAuditLog(Database(args.dsn))
        report = build_report(log, since, until, args.nature, records)
    except Exception as error:
        print(f"the report could not be assembled: {error}", file=sys.stderr)
        return 1

    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
