"""The database: the connection, the schema, and the transactions.

This is the layer that lets the project keep records instead of holding them
in memory. It is deliberately thin: a connection, a transaction, the schema
files, and the advisory lock that keeps the audit chain in one piece.

The schema lives in ``db/*.sql`` and is applied from there, in a fixed order.
The files are the source of truth — this module does not build SQL of its own
for them, it reads them.

One thing the schema cannot always do: ``db/schema.sql`` asks for the
``btree_gist`` extension, which is part of PostgreSQL's contrib and is not
present in every installation. The statements that need it are marked in the
file with a ``-- @requires-extension`` comment, and this module skips them
and says so, rather than failing half way through a schema. In a production
installation the extension is there and the exclusion constraint that prevents
overlapping slots is created.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

# The order matters: the auth schema refers to nothing, the prescription
# schema refers to the clinical tables.
# The tables the schema creates. A deployment checks them before it serves.
EXPECTED_TABLES = (
    "patient", "practitioner", "schedule_slot", "appointment", "encounter",
    "medication_request", "user_account", "auth_session", "audit_log",
    "prescription_document", "auth_lockout", "notification_outbox",
    "consent_event", "deleted_record", "deletion_audit", "transfer_logs",
)

SCHEMA_FILES = (
    "schema.sql",
    "auth_schema.sql",
    "prescription_schema.sql",
    "security_schema.sql",
    "notification_schema.sql",
    "consent_schema.sql",
    "retention_schema.sql",
    "transfer_schema.sql",
)

# The advisory lock key of the audit chain. Every writer of an audit entry
# takes it, so two writers cannot both read the same chain head.
AUDIT_LOCK_KEY = 0x7E1EC1_0A0D1  # a fixed number, not a hash of anything

REQUIRES_EXTENSION_RE = re.compile(r"^--\s*@requires-extension\s+(\w+)\s*$")
CREATE_EXTENSION_RE = re.compile(r"^CREATE EXTENSION\b", re.IGNORECASE)
DOLLAR_TAG_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


class SchemaError(RuntimeError):
    """The schema could not be applied."""


class DriverMissing(RuntimeError):
    """The PostgreSQL driver is not installed.

    The project has one dependency, and this is what happens when it is
    missing. The message says how to install it, because the alternative is
    a raw ``No module named 'psycopg'`` at the point of use.
    """


DRIVER_INSTALL = "pip install 'psycopg[binary]'"


def import_driver():
    """Import psycopg, or say what to do about it."""
    try:
        import psycopg
    except ImportError as error:
        raise DriverMissing(
            "the PostgreSQL driver is not installed. Install the project's "
            f"dependencies with: {DRIVER_INSTALL}") from error
    return psycopg


@dataclass
class SchemaReport:
    """What applying the schema did."""

    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    missing_extensions: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"applied: {', '.join(self.applied) or 'nothing'}"]
        if self.skipped:
            lines.append(f"skipped: {'; '.join(self.skipped)}")
        if self.missing_extensions:
            lines.append(f"missing extensions: {', '.join(self.missing_extensions)}")
        return "\n".join(lines)


class Database:
    """A connection to PostgreSQL, and the schema it carries."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    # -- connecting --------------------------------------------------------

    def connect(self, autocommit: bool = False):
        """Open a connection.

        psycopg is imported here, so that the module can be imported
        without the driver installed — and so that a missing driver is a
        sentence rather than an ``ImportError`` from three frames down.
        """
        psycopg = import_driver()
        return psycopg.connect(self.dsn, autocommit=autocommit)

    def check_connection(self) -> None:
        """Check that the database is there, and say so plainly if it is not."""
        try:
            with self.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
        except DriverMissing:
            raise
        except Exception as error:
            raise SchemaError(
                f"the database could not be reached: {error}") from error

    def missing_tables(self, expected=EXPECTED_TABLES) -> List[str]:
        """The tables of the schema that are not there."""
        present = set(self.tables())
        return [table for table in expected if table not in present]

    @contextmanager
    def connection(self, autocommit: bool = False):
        connection = self.connect(autocommit=autocommit)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, connection=None) -> Iterator[object]:
        """A transaction, committed on success and rolled back on failure."""
        if connection is not None:
            with connection.transaction():
                with connection.cursor() as cursor:
                    yield cursor
            return
        with self.connection() as owned:
            with owned.transaction():
                with owned.cursor() as cursor:
                    yield cursor

    # -- the schema --------------------------------------------------------

    def apply_schema(self, directory: Optional[Path] = None,
                     files: Sequence[str] = SCHEMA_FILES) -> SchemaReport:
        """Apply the schema files, in order.

        The statements that need an extension the server does not have are
        skipped, and the report says which ones. Everything else is applied
        or the whole thing fails.
        """
        directory = Path(directory) if directory else _default_schema_directory()
        report = SchemaReport()
        # Autocommit: without it, the first statement opens a transaction
        # that swallows every later one, and closing the connection rolls the
        # whole schema back. Each statement then commits on its own.
        with self.connection(autocommit=True) as connection:
            available = _available_extensions(connection)
            for name in files:
                path = directory / name
                if not path.is_file():
                    raise SchemaError(f"the schema file {path} does not exist")
                statements = _split_statements(path.read_text(encoding="utf-8"))
                for statement, required in statements:
                    if required and required not in available:
                        if required not in report.missing_extensions:
                            report.missing_extensions.append(required)
                        summary = " ".join(statement.split())[:240]
                        report.skipped.append(f"{name}: {summary} (needs {required})")
                        continue
                    with connection.transaction():
                        with connection.cursor() as cursor:
                            cursor.execute(statement)
                report.applied.append(name)
        return report

    def tables(self) -> List[str]:
        """The tables of the public schema, in alphabetical order."""
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
                return [row[0] for row in cursor.fetchall()]


def _default_schema_directory() -> Path:
    """The ``db`` directory of the repository."""
    return Path(__file__).resolve().parent.parent.parent / "db"


def _available_extensions(connection) -> set:
    with connection.cursor() as cursor:
        cursor.execute("SELECT extname FROM pg_extension")
        return {row[0] for row in cursor.fetchall()}


def _split_statements(sql: str):
    """Split a schema file into statements, with the extension each needs.

    A statement that follows a ``-- @requires-extension <name>`` comment is
    only applied when that extension is available. The comment is a comment,
    so the file is still plain SQL for anything that reads it.

    The splitter understands the two things a naive one gets wrong: a
    semicolon inside a string literal, and a semicolon inside the
    dollar-quoted body of a function. The schema of ENG-002 defines a
    trigger function that way, and splitting it on the first semicolon
    produced a syntax error rather than a function.
    """
    statements = []
    required: Optional[str] = None
    buffer: List[str] = []
    index = 0
    length = len(sql)
    in_single_quote = False
    dollar_tag: Optional[str] = None

    while index < length:
        char = sql[index]

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
                continue
            buffer.append(char)
            index += 1
            continue

        if in_single_quote:
            buffer.append(char)
            if char == "'":
                if index + 1 < length and sql[index + 1] == "'":
                    buffer.append("'")
                    index += 2
                    continue
                in_single_quote = False
            index += 1
            continue

        # Not in a string, a comment or a dollar-quoted block.
        if char == "-" and sql.startswith("--", index):
            newline = sql.find("\n", index)
            end = length if newline == -1 else newline
            line = sql[index:end].strip()
            match = REQUIRES_EXTENSION_RE.match(line)
            if match and not "".join(buffer).strip():
                required = match.group(1)
            # The comment itself is dropped, so that a semicolon inside it
            # cannot end a statement, but the newline is kept so that the
            # statement stays readable.
            buffer.append("\n")
            index = end + 1 if end < length else length
            continue

        if char == "'":
            in_single_quote = True
            buffer.append(char)
            index += 1
            continue

        if char == "$":
            match = DOLLAR_TAG_RE.match(sql, index)
            if match:
                dollar_tag = match.group(0)
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                continue

        buffer.append(char)
        if char == ";":
            statement = "".join(buffer).strip()
            buffer = []
            if statement:
                statements.append((statement, required))
            required = None
        index += 1

    if buffer:
        statement = "".join(buffer).strip()
        if statement:
            statements.append((statement, required))
    return statements


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Apply the schema: ``python3 -m telemedicine.persistence.database <dsn>``."""
    import argparse

    parser = argparse.ArgumentParser(description="Apply the telemedicine schema.")
    parser.add_argument("dsn", help="the PostgreSQL connection string")
    parser.add_argument("--directory", type=Path, default=None,
                        help="the directory holding the schema files")
    args = parser.parse_args(argv)

    report = Database(args.dsn).apply_schema(args.directory)
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
