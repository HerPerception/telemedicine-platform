"""Tests for the Nigerian dispensing identity of a medication.

A prescription is dispensed by the brand and the NAFDAC registration number
(ENG-016). These tests hold the rules for those two things:

* the registration number has a shape, and a number that could not be right
  is refused rather than printed;
* the brand and the number are both required, and the reason a prescription
  is refused does not say which of the two was left out;
* the example list is a list of examples, and every one of them has the
  right shape.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest

from telemedicine.errors import ValidationError
from telemedicine.medications import (
    EXAMPLE_MEDICATIONS,
    MISSING_DISPENSING_IDENTITY,
    NAFDAC_NUMBER_PATTERN,
    NAFDAC_SYSTEM,
    MedicationExample,
    is_valid_nafdac_number,
    validate_dispensing_identity,
    validate_nafdac_number,
)


class NafdacNumberTest(unittest.TestCase):
    def test_the_examples_of_the_shape_are_accepted(self):
        for number in ("A4-1234", "B4-5678", "04-8805", "A11-1234", "1234-56789",
                       "12-123456"):
            with self.subTest(number=number):
                self.assertTrue(is_valid_nafdac_number(number))

    def test_a_number_that_could_not_be_right_is_refused(self):
        for number in ("A4", "A4-12", "A4-1234567", "C4-1234", "A4_1234", "A-123",
                       "amoxicillin", "A4-1234-B", "4-1234A", "A4-12 34"):
            with self.subTest(number=number):
                self.assertFalse(is_valid_nafdac_number(number))

    def test_an_empty_number_is_refused(self):
        self.assertFalse(is_valid_nafdac_number(""))
        self.assertFalse(is_valid_nafdac_number(None))

    def test_the_pattern_is_the_one_the_task_asked_for(self):
        self.assertEqual(NAFDAC_NUMBER_PATTERN, r"^(A|B)?[0-9]+-[0-9]{3,6}$")

    def test_validating_returns_the_number(self):
        self.assertEqual(validate_nafdac_number(" A4-1234 "), "A4-1234")

    def test_validating_refuses_a_bad_number(self):
        with self.assertRaises(ValidationError) as caught:
            validate_nafdac_number("nonsense")
        self.assertIn("NAFDAC registration number", str(caught.exception))

    def test_validating_refuses_an_empty_number(self):
        with self.assertRaises(ValidationError) as caught:
            validate_nafdac_number("")
        self.assertIn("Cannot print", str(caught.exception))


class DispensingIdentityTest(unittest.TestCase):
    def test_the_brand_and_the_number_are_both_required(self):
        with self.assertRaises(ValidationError) as caught:
            validate_dispensing_identity("", "A4-1234")
        self.assertEqual(str(caught.exception), MISSING_DISPENSING_IDENTITY)

    def test_a_missing_number_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            validate_dispensing_identity("Emoclox", "")
        self.assertEqual(str(caught.exception), MISSING_DISPENSING_IDENTITY)

    def test_the_message_does_not_say_which_one_was_missing(self):
        messages = set()
        for brand, number in (("", "A4-1234"), ("Emoclox", "")):
            with self.assertRaises(ValidationError) as caught:
                validate_dispensing_identity(brand, number)
            messages.add(str(caught.exception))
        self.assertEqual(len(messages), 1)

    def test_the_message_says_what_the_requirement_is(self):
        self.assertIn("Cannot print", MISSING_DISPENSING_IDENTITY)
        self.assertIn("brand", MISSING_DISPENSING_IDENTITY)
        self.assertIn("NAFDAC", MISSING_DISPENSING_IDENTITY)

    def test_a_complete_identity_is_accepted(self):
        self.assertEqual(validate_dispensing_identity("Emoclox", "A4-1234"), "A4-1234")

    def test_a_bad_number_is_refused_even_with_a_brand(self):
        with self.assertRaises(ValidationError):
            validate_dispensing_identity("Emoclox", "nonsense")


class ExampleListTest(unittest.TestCase):
    def test_there_are_five_examples(self):
        self.assertEqual(len(EXAMPLE_MEDICATIONS), 5)

    def test_every_example_has_the_right_shape(self):
        for example in EXAMPLE_MEDICATIONS:
            with self.subTest(brand=example.brand_name):
                self.assertTrue(is_valid_nafdac_number(example.nafdac_number))
                self.assertTrue(example.brand_name)
                self.assertTrue(example.generic_name)
                self.assertTrue(example.rxnorm_code)

    def test_every_example_passes_the_validation(self):
        for example in EXAMPLE_MEDICATIONS:
            with self.subTest(brand=example.brand_name):
                self.assertEqual(
                    validate_dispensing_identity(example.brand_name, example.nafdac_number),
                    example.nafdac_number)

    def test_the_headline_is_the_brand_and_the_strength(self):
        example = EXAMPLE_MEDICATIONS[0]
        self.assertEqual(example.headline, "Emoclox 500mg Capsules")

    def test_the_display_is_what_the_fhir_resource_carries(self):
        example = EXAMPLE_MEDICATIONS[0]
        self.assertEqual(example.display,
                         "Emoclox [Amoxicillin 500mg] - NAFDAC: A4-1234")

    def test_the_codesystem_is_the_registration_scheme(self):
        self.assertEqual(NAFDAC_SYSTEM, "https://www.nafdac.gov.ng/registration")

    def test_an_example_can_be_built(self):
        example = MedicationExample(
            brand_name="Test", generic_name="Test 1mg", strength="1mg Tablets",
            nafdac_number="A4-1234", rxnorm_code="1", dosage_text="One tablet a day")
        self.assertEqual(example.headline, "Test 1mg Tablets")


if __name__ == "__main__":
    unittest.main()
