#!/usr/bin/env python3
"""Apply the database schema.

Usage:
    python3 scripts/apply_schema.py <dsn> [--directory DIR]

The schema lives in ``db/*.sql`` and is applied from there, in this order:

    schema.sql              the clinical tables
    auth_schema.sql         accounts, sessions and the audit log
    prescription_schema.sql the prescription document
    security_schema.sql     the shared lockout counter

The files are re-runnable: tables and indexes are created if they are not
there, and triggers are dropped and created again. Statements that need an
extension the server does not have are skipped, and the report says which
ones — see the note about ``btree_gist`` in ``db/schema.sql``.

Exit status is 0 when the schema was applied, and 1 when it was not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.persistence.database import Database, SchemaError  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dsn", help="the PostgreSQL connection string")
    parser.add_argument("--directory", type=Path, default=None,
                        help="the directory holding the schema files")
    args = parser.parse_args(argv)

    try:
        report = Database(args.dsn).apply_schema(args.directory)
    except Exception as error:
        print(f"the schema was not applied: {error}", file=sys.stderr)
        return 1

    print(report.summary())
    if report.missing_extensions:
        print()
        print("An extension was missing, so the statements that need it were skipped.")
        print("Install PostgreSQL's contrib package (postgresql-contrib) for the full")
        print("schema — the exclusion constraint that stops overlapping slots needs it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
