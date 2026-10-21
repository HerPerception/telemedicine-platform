"""The medicines a prescription has to name.

A prescription in Nigeria is dispensed by the **brand** and the **NAFDAC
registration number** — the number NAFDAC gave the product when it was
registered. A pharmacy does not dispense by an international code, and a
prescription that carries only one cannot be dispensed.

So a prescription carries two identities, and the software keeps both:

* **the coded concept** — RxNorm, with SNOMED CT or ATC alongside. This is
  what the safety checks work on: an interaction check needs a code that
  means one thing everywhere, and it is the thing that catches a duplicate
  therapy or an allergy across two prescribers.
* **the dispensing identity** — the brand name, the strength, and the NAFDAC
  registration number. This is what the patient hands over the counter.

Neither is optional. The coded concept without the dispensing identity is
a prescription the pharmacy cannot fill; the dispensing identity without the
coded concept is a medicine nothing can check.

**The NAFDAC number's shape.** The registration number is a letter or
nothing, then the applicant's number, then a hyphen, then the product's
number: ``A4-1234``, ``04-8805``, ``B11-1234``. A number that does not have
that shape is not a registration number, and a prescription that carries one
is refused rather than printed — a prescription with a wrong number is
worse than one with no number, because it looks right.

**About the examples below.** They are here for the tests, and for a client
to show while the practice's own catalogue is being built. The NAFDAC
numbers are **illustrative** — they have the right shape but are not real
registrations — and the RxNorm codes are **ingredient-level identifiers**,
not the concept for the specific product. A real prescription carries the
codes of the product that is actually dispensed. The catalogue is the
practice's job; see `docs/compliance/nigeria.md` §6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from telemedicine.errors import ValidationError

# The FHIR code system for a NAFDAC registration number. It is the
# Commission's own registration scheme; the URL is the address of the
# registration, and the code is the number on the product.
NAFDAC_SYSTEM = "https://www.nafdac.gov.ng/registration"

# The shape of a NAFDAC registration number: an optional A or B, then the
# applicant's number, a hyphen, and the product's number.
NAFDAC_NUMBER_PATTERN = r"^(A|B)?[0-9]+-[0-9]{3,6}$"
NAFDAC_NUMBER_RE = re.compile(NAFDAC_NUMBER_PATTERN)

# The message when a prescription cannot be printed because the brand or the
# NAFDAC number is missing. It is the same message wherever it is refused,
# so that nobody is left guessing which of the two is missing.
MISSING_DISPENSING_IDENTITY = (
    "Cannot print: missing brand or NAFDAC per Nigerian pharmacy requirement")


@dataclass(frozen=True)
class MedicationExample:
    """One example medicine, as it appears on a prescription."""

    brand_name: str
    generic_name: str
    strength: str
    nafdac_number: str
    rxnorm_code: str
    dosage_text: str

    @property
    def headline(self) -> str:
        """The line the document prints large: the brand and the strength."""
        return f"{self.brand_name} {self.strength}".strip()

    @property
    def display(self) -> str:
        """The line the FHIR resource carries as its text."""
        return (f"{self.brand_name} [{self.generic_name}]"
                f" - NAFDAC: {self.nafdac_number}")


# Five examples, for the tests and for a catalogue that is being built.
EXAMPLE_MEDICATIONS = (
    MedicationExample(
        brand_name="Emoclox",
        generic_name="Amoxicillin 500mg",
        strength="500mg Capsules",
        nafdac_number="A4-1234",
        rxnorm_code="723",
        dosage_text="One capsule three times a day for five days"),
    MedicationExample(
        brand_name="Paracetamol",
        generic_name="Paracetamol 500mg",
        strength="500mg Tablets",
        nafdac_number="04-8805",
        rxnorm_code="161",
        dosage_text="One tablet up to four times a day, for as long as needed"),
    MedicationExample(
        brand_name="Glucophage",
        generic_name="Metformin 500mg",
        strength="500mg Tablets",
        nafdac_number="A11-1234",
        rxnorm_code="6809",
        dosage_text="One tablet twice a day, with food"),
    MedicationExample(
        brand_name="Norvasc",
        generic_name="Amlodipine 5mg",
        strength="5mg Tablets",
        nafdac_number="B4-5678",
        rxnorm_code="274",
        dosage_text="One tablet once a day"),
    MedicationExample(
        brand_name="Ciprofloxacin",
        generic_name="Ciprofloxacin 500mg",
        strength="500mg Tablets",
        nafdac_number="04-9921",
        rxnorm_code="1308",
        dosage_text="One tablet twice a day for seven days"),
)


def is_valid_nafdac_number(number: str) -> bool:
    """Whether the string has the shape of a NAFDAC registration number."""
    if not number:
        return False
    return NAFDAC_NUMBER_RE.match(str(number).strip()) is not None


def validate_nafdac_number(number: str) -> str:
    """The registration number, if it is one.

    Raises :class:`~telemedicine.errors.ValidationError` if it is not. A
    prescription is refused rather than printed with a number that could not
    be right.
    """
    if number is None or not str(number).strip():
        raise ValidationError(MISSING_DISPENSING_IDENTITY)
    candidate = str(number).strip()
    if not is_valid_nafdac_number(candidate):
        raise ValidationError(
            f"'{candidate}' is not a NAFDAC registration number. It has to look "
            f"like A4-1234, 04-8805 or B11-1234.")
    return candidate


def validate_dispensing_identity(brand_name: str, nafdac_number: str) -> str:
    """Check the brand and the registration number, and return the number.

    Both are required: a prescription without them cannot be printed, and
    the reason is the same whichever one is missing, so that the message
    does not say which field was left out.
    """
    if not brand_name or not str(brand_name).strip():
        raise ValidationError(MISSING_DISPENSING_IDENTITY)
    if not nafdac_number or not str(nafdac_number).strip():
        raise ValidationError(MISSING_DISPENSING_IDENTITY)
    return validate_nafdac_number(nafdac_number)
