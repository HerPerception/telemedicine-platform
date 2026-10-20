"""Tests for the ENG-002 authentication and audit schema file.

The schema cannot be executed here (no PostgreSQL server is available in the
development environment), so these tests check the file's structure: the
tables, keys, constraints and append-only protections that
``docs/auth-design.md`` promises. They are a guard against typos and
accidental deletions, not a substitute for running the DDL against a real
server.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "db" / "auth_schema.sql"

EXPECTED_TABLES = {"user_account", "auth_session", "audit_log"}


def strip_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def parse_tables(sql):
    sql = strip_comments(sql)
    tables = {}
    pattern = re.compile(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)\s*\((.*?)\n\);",
                     re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(sql):
        body = [line.strip() for line in match.group(2).splitlines() if line.strip()]
        tables[match.group(1)] = body
    return tables


class AuthSchemaStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.clean = strip_comments(cls.sql)
        cls.tables = parse_tables(cls.sql)

    def test_all_three_tables_are_defined(self):
        self.assertEqual(set(self.tables), EXPECTED_TABLES)

    def test_accounts_and_sessions_have_uuid_primary_keys(self):
        for name in ("user_account", "auth_session"):
            with self.subTest(table=name):
                primary_keys = [line for line in self.tables[name] if "PRIMARY KEY" in line]
                self.assertEqual(len(primary_keys), 1)
                self.assertIn("uuid", primary_keys[0])

    def test_the_audit_log_is_ordered_by_a_monotonic_sequence(self):
        # The chain is ordered by sequence, so the audit log uses a bigserial
        # key rather than a UUID: the order of the log must be the order of
        # the keys.
        primary_keys = [line for line in self.tables["audit_log"] if "PRIMARY KEY" in line]
        self.assertEqual(len(primary_keys), 1)
        self.assertIn("bigserial", primary_keys[0])

    def test_user_account_stores_no_plaintext_password(self):
        body = "\n".join(self.tables["user_account"])
        self.assertIn("password_hash", body)
        self.assertNotIn("password text", body.lower())
        self.assertNotIn("password varchar", body.lower())

    def test_user_account_encodes_the_hash_algorithm(self):
        body = "\n".join(self.tables["user_account"])
        self.assertIn("pbkdf2_sha256", body)
        self.assertIn("CHECK (password_hash LIKE 'pbkdf2_sha256$%')", body)

    def test_user_account_restricts_the_role(self):
        body = "\n".join(self.tables["user_account"])
        self.assertIn("role", body)
        self.assertRegex(body, r"role\s+text\s+NOT NULL CHECK \(role IN \('patient', 'practitioner'\)\)")

    def test_email_uniqueness_is_case_insensitive(self):
        self.assertIn("user_account_email_lower_key", self.clean)
        self.assertIn("lower(email)", self.clean)

    def test_sessions_store_only_a_token_digest(self):
        body = "\n".join(self.tables["auth_session"])
        self.assertIn("token_hash", body)
        self.assertRegex(body, r"token_hash\s+char\(64\)\s+NOT NULL UNIQUE")
        self.assertNotIn("token text", body.lower())

    def test_sessions_cannot_outlive_their_creation(self):
        body = "\n".join(self.tables["auth_session"])
        self.assertIn("auth_session_expiry_after_creation", body)
        self.assertIn("expires_at > created_at", body)

    def test_audit_log_records_outcomes_from_a_fixed_set(self):
        body = "\n".join(self.tables["audit_log"])
        self.assertRegex(body, r"outcome\s+text\s+NOT NULL CHECK \(outcome IN "
                               r"\('success', 'denied', 'error'\)\)")

    def test_audit_log_stores_the_hash_chain_columns(self):
        body = "\n".join(self.tables["audit_log"])
        self.assertIn("previous_hash", body)
        self.assertIn("entry_hash", body)
        self.assertIn("previous_hash ~ '^[0-9a-f]{64}$'", body)
        self.assertIn("entry_hash ~ '^[0-9a-f]{64}$'", body)

    def test_audit_log_is_append_only(self):
        self.assertIn("audit_log_is_append_only", self.clean)
        self.assertRegex(self.clean, r"BEFORE UPDATE OR DELETE ON audit_log")
        self.assertRegex(self.clean, r"BEFORE TRUNCATE ON audit_log")
        self.assertIn("RAISE EXCEPTION 'audit_log is append-only", self.clean)

    def test_audit_log_has_no_delete_path_in_the_schema(self):
        body = "\n".join(self.tables["audit_log"])
        self.assertNotIn("ON DELETE CASCADE", body.upper())

    def test_audit_log_is_indexed_for_the_lookups_the_audit_queries_make(self):
        for index in ("audit_log_resource", "audit_log_actor", "audit_log_occurred",
                      "audit_log_denied"):
            with self.subTest(index=index):
                self.assertIn(index, self.clean)

    def test_the_schema_does_not_change_the_clinical_tables(self):
        # ENG-002 must not touch ENG-001's tables; the link is the opaque
        # account_ref column, not a foreign key.
        self.assertNotIn("REFERENCES patient", self.clean)
        self.assertNotIn("REFERENCES practitioner", self.clean)
        self.assertNotIn("ALTER TABLE", self.clean.upper())

    def test_the_account_link_to_the_clinical_record_is_opaque(self):
        body = "\n".join(self.tables["user_account"])
        self.assertIn("account_ref", body)
        self.assertNotRegex(body, r"account_ref\s+\w+.*REFERENCES")

    def test_sessions_are_cascade_deleted_with_their_account(self):
        body = "\n".join(self.tables["auth_session"])
        self.assertIn("ON DELETE CASCADE", body.upper())


if __name__ == "__main__":
    unittest.main()
