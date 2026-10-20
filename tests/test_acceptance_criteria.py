"""The traceability check of QA-001.

This test reads ``docs/acceptance-traceability.md`` and makes sure it is
true. It fails when:

* an acceptance criterion is missing from the document;
* a criterion marked ``covered`` names a test that does not exist, or a
  class or a method that has been renamed;
* a criterion that is only partly covered, or not covered at all, gives no
  reason;
* a criterion has no owning feature;
* the CI workflow is missing, or has stopped running the suite or the
  validator.

The point is that a criterion which quietly loses its test fails the build
rather than reaching a patient untested.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import importlib.util
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACEABILITY_PATH = REPO_ROOT / "docs" / "acceptance-traceability.md"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The criteria the MVP has. The ids are frozen here so that a criterion
# cannot be quietly dropped from the document; the text lives in the
# document, which is what people read.
EXPECTED_CRITERIA = (
    "AC-BOOK-01", "AC-BOOK-02", "AC-BOOK-03", "AC-BOOK-04", "AC-BOOK-05", "AC-BOOK-06",
    "AC-VIDEO-01", "AC-VIDEO-02", "AC-VIDEO-03",
    "AC-RX-01", "AC-RX-02", "AC-RX-03", "AC-RX-04", "AC-RX-05", "AC-RX-06",
    "AC-FHIR-01", "AC-FHIR-02", "AC-FHIR-03", "AC-FHIR-04", "AC-FHIR-05", "AC-FHIR-06",
    "AC-SEC-01", "AC-SEC-02", "AC-SEC-03", "AC-SEC-04", "AC-SEC-05", "AC-SEC-06",
    "AC-DATA-01", "AC-DATA-02",
    "AC-GATE-01", "AC-GATE-02", "AC-GATE-03", "AC-GATE-04", "AC-GATE-05", "AC-GATE-06",
    "AC-GATE-07", "AC-GATE-08", "AC-GATE-09", "AC-GATE-10", "AC-GATE-11",
)

STATUSES = ("covered", "partial", "not covered")

TEST_REFERENCE_RE = re.compile(r"^(?P<path>[\w/\.]+\.py)::(?P<class>\w+)::(?P<method>test_\w+)$")


def parse_rows(text):
    """The criterion rows of the traceability document.

    The cells are stripped of their backticks, so that a reference in the
    document reads the same as it does in the test.
    """
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("| AC-"):
            continue
        cells = [cell.strip().strip("`").strip() for cell in line.strip("|").split("|")]
        rows.append(cells)
    return rows


def _references(cell):
    """The test references of a cell, without their backticks."""
    return [item.strip().strip("`").strip()
            for item in cell.split(";")
            if item.strip().strip("`").strip()]


def load_module(path: Path):
    """Import a test module by path, the way the runner would."""
    name = "traceability_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TraceabilityDocumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = TRACEABILITY_PATH.read_text(encoding="utf-8")
        cls.rows = parse_rows(cls.text)

    def test_the_document_exists(self):
        self.assertTrue(TRACEABILITY_PATH.is_file(),
                        "docs/acceptance-traceability.md is missing")

    def test_every_criterion_is_in_the_document(self):
        found = {row[0] for row in self.rows}
        missing = [criterion for criterion in EXPECTED_CRITERIA if criterion not in found]
        self.assertEqual(missing, [], f"criteria missing from the document: {missing}")

    def test_no_criterion_is_invented(self):
        known = set(EXPECTED_CRITERIA)
        invented = sorted({row[0] for row in self.rows} - known)
        self.assertEqual(invented, [], f"criteria that are not part of the MVP: {invented}")

    def test_every_criterion_appears_once(self):
        ids = [row[0] for row in self.rows]
        duplicates = sorted({criterion for criterion in ids if ids.count(criterion) > 1})
        self.assertEqual(duplicates, [], f"criteria listed more than once: {duplicates}")

    def test_every_row_is_complete(self):
        for row in self.rows:
            criterion = row[0]
            with self.subTest(criterion=criterion):
                self.assertGreaterEqual(len(row), 6, f"{criterion} has too few columns")
                self.assertTrue(row[1], f"{criterion} has no criterion text")
                self.assertIn(row[2], STATUSES,
                              f"{criterion} has the status '{row[2]}', which is not one of "
                              f"{STATUSES}")
                self.assertTrue(row[4], f"{criterion} names no owning feature")

    def test_a_covered_criterion_names_at_least_one_test(self):
        for row in self.rows:
            if row[2] != "covered":
                continue
            with self.subTest(criterion=row[0]):
                self.assertNotIn(row[3], ("", "—"),
                                 f"{row[0]} is marked covered but names no test")

    def test_an_uncovered_criterion_says_why(self):
        for row in self.rows:
            if row[2] == "covered":
                continue
            with self.subTest(criterion=row[0]):
                self.assertNotIn(row[5], ("", "—"),
                                 f"{row[0]} is marked '{row[2]}' but gives no reason")

    def test_every_named_test_exists(self):
        modules = {}
        for row in self.rows:
            if row[2] != "covered":
                continue
            for reference in _references(row[3]):
                with self.subTest(criterion=row[0], test=reference):
                    match = TEST_REFERENCE_RE.match(reference)
                    self.assertIsNotNone(
                        match, f"{row[0]} names '{reference}', which is not a "
                               f"'path::Class::test_name' reference")
                    path = REPO_ROOT / match.group("path")
                    self.assertTrue(path.is_file(), f"{reference} names a file that does not exist")
                    if path not in modules:
                        modules[path] = load_module(path)
                    module = modules[path]
                    self.assertTrue(
                        hasattr(module, match.group("class")),
                        f"{reference} names a class that does not exist")
                    klass = getattr(module, match.group("class"))
                    self.assertTrue(
                        hasattr(klass, match.group("method")),
                        f"{reference} names a test that does not exist")

    def test_the_tests_named_are_tests_of_this_repository(self):
        for row in self.rows:
            if row[2] != "covered":
                continue
            for reference in _references(row[3]):
                with self.subTest(criterion=row[0], test=reference):
                    self.assertTrue(reference.startswith("tests/"),
                                    f"{reference} does not name a test of this repository")

    def test_the_document_says_where_the_criteria_come_from(self):
        self.assertIn("source of truth", self.text)
        self.assertIn("README", self.text)


class ContinuousIntegrationTest(unittest.TestCase):
    """The suite has to run somewhere other than on a developer's machine."""

    def test_the_workflow_exists(self):
        self.assertTrue(CI_PATH.is_file(), ".github/workflows/ci.yml is missing")

    def test_the_workflow_runs_the_test_suite(self):
        text = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover -s tests", text)

    def test_the_workflow_runs_the_fhir_validator(self):
        text = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python3 scripts/validate_fhir_examples.py", text)

    def test_the_workflow_runs_on_pull_requests_and_on_main(self):
        text = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("pull_request:", text)
        self.assertIn("push:", text)
        self.assertIn("main", text)

    def test_the_workflow_pins_a_python_version(self):
        text = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("python-version", text)
        self.assertIn("3.12", text)


if __name__ == "__main__":
    unittest.main()
