# ENG-016: the prescription names the medicine the way a pharmacy dispenses it

A prescription in Nigeria is dispensed by the brand and the NAFDAC
registration number. One that carries only a coded concept cannot be
dispensed, so the coded concept is not enough: the local identity has to be
on the prescription as well.

The database now carries it:

  brand_name     text NOT NULL   the brand the product is sold under
  generic_name   text NOT NULL   the generic name and the strength
  strength       text            "500mg Capsules"
  nafdac_number  text NOT NULL   A4-1234, 04-8805, B11-1234

The registration number has a shape -- an optional A or B, the applicant's
number, a hyphen, and the product's number -- and the database refuses one
that does not have it: a number that could not be right is worse than no
number, because it looks right. The constraint is added NOT VALID, so a
database that already holds prescriptions is upgraded rather than rejected,
and the rows written after the upgrade are checked.

The FHIR resource carries two codings: the coded concept first, so a client
that reads the first coding reads what it read before, and the NAFDAC
registration number second, in the code system
https://www.nafdac.gov.ng/registration. The text says all three things --
"Emoclox [Amoxicillin 500mg] - NAFDAC: A4-1234" -- and the structured values
are carried as three extensions, because R4 has no element for the brand a
product is sold under and parsing them out of the text would be fragile.

The document prints the medicine the way a pharmacy reads it:

  Emoclox 500mg Capsules      the brand and the strength, large and bold
  [Amoxicillin 500mg]         the generic name
  NAFDAC REG NO: A4-1234       the registration number

A prescription without a brand or without a registration number is not
printed at all. The refusal is "Cannot print: missing brand or NAFDAC per
Nigerian pharmacy requirement", and the same message is used whichever of
the two is missing, so that nobody is left guessing which field was left
out.

telemedicine/medications.py holds the rule and five example medicines, with
illustrative registration numbers and ingredient-level codes: they are
examples for the tests, and the catalogue of what the practice actually
dispenses is the practice's own.

One thing moved: the authorization is now decided before the content is
checked, so that a refused attempt is audited as a refusal whatever the
body said.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
