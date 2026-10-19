"""Tests for the ENG-001 PostgreSQL schema file.

The schema cannot be executed here (no PostgreSQL server is available in the
development environment), so these tests check the file's structure: the
tables, keys, foreign keys and constraints that the data model document
promises. They are a guard against typos and accidental deletions, not a
substitute for running the DDL against a real server.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"

EXPECTED_TABLES = {
    "patient",
    "practitioner",
    "schedule_slot",
    "appointment",
    "encounter",
    "medication_request",
}


def strip_comments(sql):
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def parse_tables(sql):
    """Return {table_name: [body lines]} for every CREATE TABLE statement."""
    sql = strip_comments(sql)
    tables = {}
    pattern = re.compile(r"CREATE TABLE\s+(\w+)\s*\((.*?)\n\);", re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(sql):
        name = match.group(1)
        body = [line.strip() for line in match.group(2).splitlines() if line.strip()]
        tables[name] = body
    return tables


class SchemaStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.clean = strip_comments(cls.sql)
        cls.tables = parse_tables(cls.sql)

    def test_all_six_tables_are_defined(self):
        self.assertEqual(set(self.tables), EXPECTED_TABLES)

    def test_every_table_has_a_uuid_primary_key(self):
        for name, body in self.tables.items():
            with self.subTest(table=name):
                primary_keys = [line for line in body if "PRIMARY KEY" in line]
                self.assertEqual(len(primary_keys), 1, f"{name} must have exactly one primary key")
                self.assertIn("uuid", primary_keys[0])

    def test_every_table_has_created_and_updated_timestamps(self):
        for name, body in self.tables.items():
            with self.subTest(table=name):
                joined = "\n".join(body)
                self.assertIn("created_at", joined)
                self.assertIn("updated_at", joined)

    def test_foreign_keys_refer_to_declared_tables(self):
        referenced = set(re.findall(r"REFERENCES\s+(\w+)\s*\(", self.clean, re.IGNORECASE))
        self.assertTrue(referenced)
        for table in referenced:
            with self.subTest(table=table):
                self.assertIn(table, self.tables)

    def test_clinical_data_is_never_cascade_deleted(self):
        self.assertNotIn("ON DELETE CASCADE", self.clean.upper())
        self.assertIn("ON DELETE RESTRICT", self.clean.upper())

    def test_no_autoincrementing_integer_keys(self):
        self.assertNotIn("SERIAL", self.clean.upper())

    def test_slots_cannot_overlap_for_one_practitioner(self):
        self.assertIn("EXCLUDE USING gist", self.clean)
        self.assertIn("schedule_slot_no_overlap", self.clean)

    def test_appointment_slot_is_unique(self):
        appointment = "\n".join(self.tables["appointment"])
        self.assertRegex(appointment, r"slot_id\s+uuid\s+NOT NULL UNIQUE")

    def test_appointment_window_must_match_the_slot(self):
        self.assertIn("appointment_slot_match", self.clean)
        self.assertIn("schedule_slot_identity", self.clean)

    def test_encounter_and_prescription_keep_their_parents_consistent(self):
        self.assertIn("encounter_appointment_match", self.clean)
        self.assertIn("medication_request_encounter_match", self.clean)
        self.assertIn("encounter_id", "\n".join(self.tables["medication_request"]))

    def test_cancelled_appointments_need_a_reason(self):
        self.assertIn("appointment_cancelled_has_reason", self.clean)

    def test_status_columns_are_constrained_to_known_values(self):
        for table, column in (("appointment", "status"), ("encounter", "status"),
                              ("medication_request", "status"),
                              ("medication_request", "intent"),
                              ("schedule_slot", "status")):
            with self.subTest(table=table, column=column):
                body = "\n".join(self.tables[table])
                pattern = rf"(?s){column}\s+text\s+NOT NULL.*?CHECK"
                self.assertRegex(body, pattern)

    def test_gen_random_uuid_is_available(self):
        self.assertIn("gen_random_uuid()", self.clean)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS btree_gist", self.clean)


if __name__ == "__main__":
    unittest.main()
