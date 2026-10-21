#!/usr/bin/env python3
"""The retention job: what is past its period, and (only if the policy says so)
what goes.

Usage:
    python3 scripts/retention.py check [--dry-run] [--policy FILE] [--dsn DSN]
    python3 scripts/retention.py delete [--policy FILE] [--dsn DSN]

**Nothing is deleted while the policy file says what it says.** The policy
carries two flags, and both have to be true before a single record is
removed: `enabled` and `legal_advisor_signed`. The numbers in the file are
conventional practice, not law — they are placeholders until the practice's
adviser confirms them, and the file says so at the top.

What each command does:

* **check** finds the records that are past their period and prints them. With
  `--dry-run` it only prints them. Without it, it removes them *only* if the
  policy allows it; a policy that is switched on but not signed is refused
  outright, because that is the state that looks like the job is running and
  is not.
* **delete** removes what is past its period, in two steps: the record is
  moved to the trash and marked, and it is removed for good thirty days
  later. It refuses to do anything unless both flags are true.

Every removal — soft or hard — is written to an immutable table, with the
reason.

The exit status is 0 when the command did what it was asked to do, and 1 when
it refused: a job that could not do its work must not look like a job that
had nothing to do.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.retention import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    RECORD_AUDIT_LOG,
    RECORD_CLINICAL,
    RECORD_PRESCRIPTION_DOCUMENT,
    RetentionCandidate,
    RetentionPolicyError,
    RetentionRefused,
    find_candidates,
    hard_delete,
    load_policy,
    soft_delete,
)

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "delete"),
                        help="check: what is past its period; delete: remove it")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen, and change nothing")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH,
                        help=f"the policy file (default: {DEFAULT_POLICY_PATH})")
    parser.add_argument("--dsn", default=None,
                        help="the PostgreSQL connection string. Without it, the "
                             "records in memory are used, and nothing is written")
    parser.add_argument("--now", default=None,
                        help="the moment to measure from, as an ISO 8601 instant "
                             "(default: now)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policy = load_policy(args.policy)
    except RetentionPolicyError as error:
        print(f"The retention policy could not be read: {error}", file=sys.stderr)
        return EXIT_ERROR

    now = _parse_moment(args.now) if args.now else datetime.now(timezone.utc)

    print(f"Retention policy: {policy.source_path}")
    print(f"  enabled: {policy.enabled}   legal_advisor_signed: "
          f"{policy.legal_advisor_signed}")
    print(f"  adult outpatient {policy.adult_outpatient_years} years, "
          f"adult inpatient {policy.adult_inpatient_years} years, "
          f"children until {policy.child_until_age}, "
          f"prescriptions {policy.prescription_years} years, "
          f"audit trail {policy.audit_log_years} years")
    if not policy.legal_advisor_signed:
        print("  The numbers are placeholders until a qualified adviser has "
              "confirmed them.")
    print()

    try:
        if args.command == "check":
            return _check(args, policy, now)
        return _delete(args, policy, now)
    except RetentionRefused as error:
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


def _check(args, policy, now) -> int:
    """Report what is past its period."""
    source, store = _sources(args)
    candidates = find_candidates(source, policy, now)
    _print_candidates(candidates)

    deletable = [candidate for candidate in candidates if candidate.deletable]
    print()
    print(f"Would delete {len(deletable)} records")

    if args.dry_run:
        print("(dry run: nothing was changed)")
        return EXIT_OK

    if not policy.enabled:
        # The policy is not in force. The report is the whole of the job.
        print("(the policy is switched off: nothing was deleted)")
        return EXIT_OK

    # Switched on, but not signed: refused outright, because that is the
    # state that looks like the job is running and is not.
    policy.check_may_delete()

    entries = soft_delete(deletable, store, source, policy, now)
    print(f"Soft-deleted {len(entries)} records into the trash. They may be "
          f"purged 30 days from now.")
    return EXIT_OK


def _delete(args, policy, now) -> int:
    """Remove what is past its period, in two steps."""
    policy.check_may_delete()
    source, store = _sources(args)
    candidates = find_candidates(source, policy, now)
    _print_candidates(candidates)

    deletable = [candidate for candidate in candidates if candidate.deletable]
    print()
    print(f"Would delete {len(deletable)} records")

    soft = soft_delete(deletable, store, source, policy, now)
    print(f"Soft-deleted {len(soft)} records into the trash.")

    hard = hard_delete(store, policy, now)
    if hard:
        print(f"Removed {len(hard)} records for good: their 30 day grace "
              f"period had passed.")
    else:
        print("Nothing was due for removal: no record has been in the trash "
              "for 30 days.")
    return EXIT_OK


def _print_candidates(candidates) -> None:
    if not candidates:
        print("Nothing is past its period.")
        return
    by_type = {}
    for candidate in candidates:
        by_type.setdefault(candidate.record_type, []).append(candidate)
    for record_type in sorted(by_type):
        entries = by_type[record_type]
        print(f"{record_type}: {len(entries)}")
        for candidate in entries:
            marker = "" if candidate.deletable else "  (not removed)"
            print(f"  {candidate.record_id}: {candidate.reason}{marker}")
            if candidate.note:
                print(f"    {candidate.note}")


def _sources(args):
    """The records to read, and where the trash goes."""
    if args.dsn:
        from telemedicine.application import build_application
        from telemedicine.config import Settings
        from telemedicine.persistence.retention_store import PostgresRetentionStore
        from telemedicine.retention import ServiceRetentionSource

        application = build_application(Settings(database_url=args.dsn))
        source = ServiceRetentionSource(application.records,
                                         application.prescriptions,
                                         application.audit)
        store = PostgresRetentionStore(application.database)
        return source, store

    from telemedicine.records import RecordsService
    from telemedicine.retention import InMemoryRetentionStore, ServiceRetentionSource

    records = RecordsService()
    return ServiceRetentionSource(records), InMemoryRetentionStore()


def _parse_moment(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
