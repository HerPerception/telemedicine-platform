"""Tests for the compliance documents.

Two documents carry the Nigerian answer: `docs/compliance/nigeria.md`, which
says what the law requires and what the practice has to decide, and
`docs/compliance/privacy-notice-draft.md`, which is the draft wording.

Both are read by people — a patient, an adviser, a practitioner — and both
make promises about the law. These tests hold them to it:

* the answer must name the jurisdiction and the sections it rests on;
* the notice must cover every one of the seven things section 27(1) of the
  Nigeria Data Protection Act 2023 says the patient must be told;
* the optional uses must each have their own consent;
* nothing may be presented as settled that is not.

A document that quietly loses a requirement is worse than no document,
because it is trusted.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSWER_PATH = REPO_ROOT / "docs" / "compliance" / "nigeria.md"
NOTICE_PATH = REPO_ROOT / "docs" / "compliance" / "privacy-notice-draft.md"


class ComplianceAnswerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = ANSWER_PATH.read_text(encoding="utf-8")

    def test_the_answer_exists(self):
        self.assertTrue(ANSWER_PATH.is_file(),
                        "docs/compliance/nigeria.md is missing")

    def test_it_names_the_jurisdiction(self):
        self.assertIn("Nigeria", self.text)

    def test_it_cites_the_law_it_rests_on(self):
        for marker in ("Section 30(1)(g)", "Section 30(1)(a)", "Section 27",
                       "Section 32", "Section 35", "Section 40", "Section 41",
                       "Section 44"):
            with self.subTest(section=marker):
                self.assertTrue(marker in self.text,
                                f"the answer does not cite {marker}")

    def test_it_names_the_sources(self):
        for marker in ("ndpc.gov.ng", "Nigeria_Data_Protection_Act_2023.pdf",
                       "nig162642.pdf", "Nigeria-Core"):
            with self.subTest(source=marker):
                self.assertIn(marker, self.text)

    def test_it_answers_the_questions_the_practice_asked(self):
        for marker in ("drug code", "consent", "retention", "video provider"):
            with self.subTest(question=marker):
                self.assertIn(marker, self.text.lower())

    def test_it_says_what_is_still_not_settled(self):
        self.assertIn("still not settled", self.text)
        self.assertIn("adviser", self.text)

    def test_it_says_the_media_server_is_run_by_the_practice(self):
        self.assertIn("A server you run, in Nigeria", self.text)

    def test_it_says_the_dpo_is_a_person(self):
        self.assertIn("This is a person, not a feature", self.text)


class PrivacyNoticeDraftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = NOTICE_PATH.read_text(encoding="utf-8")

    def test_the_draft_exists(self):
        self.assertTrue(NOTICE_PATH.is_file(),
                        "docs/compliance/privacy-notice-draft.md is missing")

    def test_it_is_marked_as_a_draft(self):
        self.assertIn("This is a draft", self.text)
        self.assertIn("not wording to use", self.text)

    def test_it_covers_the_seven_requirements_of_section_27(self):
        # Section 27(1) says the patient must be told: (a) who the
        # controller is, (b) the lawful basis and the purposes, (c) the
        # recipients, (d) the rights, (e) the retention period, (f) the
        # right to complain to the Commission, and (g) any automated
        # decision-making.
        for marker in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)"):
            with self.subTest(paragraph=marker):
                self.assertTrue(f"(Section 27(1){marker}" in self.text,
                                f"the notice does not answer Section 27(1){marker}")

    def test_it_names_the_commission_and_how_to_reach_it(self):
        self.assertIn("Nigeria Data Protection Commission", self.text)
        self.assertIn("ndpc.gov.ng", self.text)
        self.assertIn("info@ndpc.gov.ng", self.text)

    def test_it_has_a_consent_for_each_optional_purpose(self):
        for marker in ("Consent A", "Consent B", "Consent C", "Consent D"):
            with self.subTest(consent=marker):
                self.assertIn(marker, self.text)

    def test_each_consent_says_the_patient_may_decline(self):
        self.assertIn("my care will not be affected", self.text)

    def test_each_consent_says_how_to_withdraw(self):
        self.assertIn("withdraw this at any time", self.text)

    def test_it_states_the_retention_periods(self):
        self.assertIn("How long we keep your data", self.text)
        self.assertIn("to be confirmed", self.text)

    def test_it_says_nothing_is_deleted_until_the_periods_are_confirmed(self):
        self.assertIn("nothing is deleted", self.text.lower())

    def test_it_marks_what_the_practice_still_has_to_do(self):
        self.assertIn("What the practice still has to do", self.text)


if __name__ == "__main__":
    unittest.main()
