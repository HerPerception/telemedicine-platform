# ENG-022: the demo mode, and the list of what is waiting for a lawyer

The practice has no legal adviser yet. That is not a reason to leave the
documents unmarked, so every prescription now says on its face:

    DEMO - NOT FOR REAL PATIENTS

TELEMEDICINE_DEMO_MODE is **on by default**, and it is off only when the
practice says so. A prescription that could be mistaken for a real one is
worse than one that says plainly that it is not.

TODO_LEGAL.md is the list of what is waiting, in the place a person would
look for it:

* the retention numbers -- conventional practice, not law, waiting on the
  National Health Act 2014 and the Medical and Dental Council, and on the
  adviser's signature. Nothing is deleted until both flags are true;
* the cross-border justifications -- every service outside Nigeria is
  blocked until the adviser says what the basis is, and the reason is
  recorded;
* the privacy notice -- a draft, answering all seven requirements of
  section 27(1), and marked "DRAFT - pending legal advisor";
* and the recommendation: host everything in Nigeria, and use test data
  until the lawyer has reviewed.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
