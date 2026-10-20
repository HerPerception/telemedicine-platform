"""Tests for the ENG-005 prescription document schema.

The schema cannot be executed here (no PostgreSQL server is available in the
development environment), so these tests check the file's structure: the
table, its keys, the constraints and the immutability protection that
``docs/prescription-design.md`` promises. They are a guard against typos and
accidental deletions, not a substitute for running the DDL against a real
server.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "db" / "prescription_schema.sql"
CLINICAL_SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"


def strip_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def parse_tables(sql):
    sql = strip_comments(sql)
    tables = {}
    pattern = re.compile(r"CREATE TABLE\s+(\w+)\s*\((.*?)\n\);", re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(sql):
        body = [line.strip() for line in match.group(2).splitlines() if line.strip()]
        tables[match.group(1)] = body
    return tables


class PrescriptionSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.clean = strip_comments(cls.sql)
        cls.tables = parse_tables(cls.sql)

    def test_the_document_table_is_defined(self):
        self.assertIn("prescription_document", self.tables)

    def test_the_document_has_a_uuid_primary_key(self):
        primary_keys = [line for line in self.tables["prescription_document"]
                        if "PRIMARY KEY" in line]
        self.assertEqual(len(primary_keys), 1)
        self.assertIn("uuid", primary_keys[0])

    def test_a_document_belongs_to_exactly_one_prescription(self):
        body = "\n".join(self.tables["prescription_document"])
        self.assertRegex(body, r"medication_request_id\s+uuid\s+NOT NULL UNIQUE")
        self.assertIn("REFERENCES medication_request (id) ON DELETE RESTRICT", body)

    def test_a_document_is_never_deleted_with_its_prescription(self):
        body = "\n".join(self.tables["prescription_document"])
        self.assertNotIn("ON DELETE CASCADE", body.upper())

    def test_the_checksum_is_stored_and_constrained(self):
        body = "\n".join(self.tables["prescription_document"])
        self.assertIn("checksum", body)
        self.assertIn("CHECK (checksum ~ '^[0-9a-f]{64}$')", body)

    def test_the_document_size_must_be_positive(self):
        body = "\n".join(self.tables["prescription_document"])
        self.assertIn("byte_size", body)
        self.assertIn("CHECK (byte_size > 0)", body)

    def test_the_storage_key_is_required(self):
        body = "\n".join(self.tables["prescription_document"])
        self.assertRegex(body, r"storage_key\s+text\s+NOT NULL")
        self.assertIn("CHECK (storage_key <> '')", body)

    def test_the_content_type_defaults_to_pdf(self):
        body = "\n".join(self.tables["prescription_document"])
        self.assertIn("content_type", body)
        self.assertIn("application/pdf", body)

    def test_the_status_the_document_was_rendered_from_is_kept(self):
        body = "\n".join(self.tables["prescription_document"])
        self.assertIn("rendered_from_status", body)

    def test_a_document_cannot_be_rewritten(self):
        self.assertIn("prescription_document_is_immutable", self.clean)
        self.assertRegex(self.clean, r"BEFORE UPDATE ON prescription_document")
        self.assertIn("RAISE EXCEPTION 'prescription_document rows are immutable", self.clean)

    def test_the_schema_does_not_change_the_clinical_tables(self):
        self.assertNotIn("ALTER TABLE", self.clean.upper())
        self.assertNotIn("CREATE TABLE medication_request", self.clean)

    def test_the_prescription_table_it_references_exists(self):
        clinical = strip_comments(CLINICAL_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("medication_request", parse_tables(clinical))


if __name__ == "__main__":
    unittest.main()
