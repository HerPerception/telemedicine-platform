# OPS-003: the Nigerian answer — consent capture, the breach report, the law

The practice answered the four questions the compliance review was waiting
on. The jurisdiction is Nigeria. This branch answers them against the law,
read from the official texts, and builds the two pieces of machinery the law
puts a clock on.

The answers (docs/compliance/nigeria.md):

* the clinical record does not rest on consent. Section 30(1)(g) of the
  Nigeria Data Protection Act 2023 allows processing of sensitive personal
  data — health status is sensitive personal data — where it is carried out
  for purposes of medical care under the responsibility of a professional
  owing a duty of confidentiality. So the consultation is made under that
  ground, and the patient is told about it through the section 27 notice.
  Consent is for the optional uses only, one purpose at a time, each
  withdrawable on its own under section 35. The practice asked for "one form
  covering everything"; the law points to a different shape, and the
  document says why, in plain words.
* retention: section 27(1)(e) requires the notice to state a period, and
  the clinical period is health-sector law, not data protection law. The
  draft schedule is in the answer; the period could not be read from the
  gazette scan, and the document says so rather than guessing. Nothing is
  deleted until the numbers are confirmed.
* medicines: there is no national medication terminology in force yet, so a
  prescription carries both an international code (RxNorm, with SNOMED CT or
  ATC alongside) for the safety checks and the local identity (brand name and
  NAFDAC number) for dispensing. The statutory list is the Essential Drugs
  List under section 39 of the National Health Act 2014.
* the video provider: section 41 forbids transferring personal data out of
  Nigeria without an adequate basis, and section 44 requires the country of
  any transfer to be named in the registration. So the media server is to be
  run by the practice, in Nigeria.

What is built:

* telemedicine/consent.py — the consent record. A consent per optional
  purpose, each withdrawable on its own, the notice acknowledgement kept
  apart from the consents, and every event audited. The record is
  append-only, like the audit log: a withdrawal is a new row, not a change to
  the old one.
* db/consent_schema.sql — the table, with the database refusing an update,
  a delete and a truncate on it.
* scripts/report_breach.py — assembles the section 40(2) report from the
  audit log: the categories and approximate numbers of data subjects and
  records concerned. It leaves the consequences and the measures to the
  controller, and says so on the face of the report.
* docs/compliance/privacy-notice-draft.md — the draft notice, answering all
  seven requirements of section 27(1), and the four optional-use consents,
  each on its own form. Marked as a draft: the wording is for an adviser to
  mark up.

Two corrections found on the way:

* the traceability document had a corrupted row — AC-SEC-09's tail pasted
  into AC-SEC-10 — which the check did not catch, because it only asked for
  six columns or more. It now asks for exactly six.
* the summary in the remediation status was stale: it counted 37 findings
  and 6 closed, while the tables held 41 findings and 10 closed. It now
  counts 43, 14 closed, 8 partly closed, 21 open, and the counts are
  checked against the tables.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
