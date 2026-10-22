# QA-001: a test for every acceptance criterion, and CI that runs the suite

The acceptance criteria of the MVP were written down in the README and in
the backlog, and nothing connected them to the tests. A criterion could
quietly lose its test and nobody would notice.

* docs/acceptance-traceability.md - every acceptance criterion of the MVP,
  whether a test covers it and which one, and, where it is not covered,
  why not. The criteria are the ones of the README's scope table and its
  non-functional gates, reproduced here because the README in main is a
  two-line stub.
* tests/test_acceptance_criteria.py - the check that keeps the document
  true. It fails when a criterion is missing, when a covered criterion
  names a test that does not exist, when an uncovered criterion gives no
  reason, or when CI stops running the suite. It caught two wrong test
  names in the document while it was being written.
* .github/workflows/ci.yml - the suite, the validator and the traceability
  check, on every push to main and on every pull request.

Of the forty criteria, twenty-seven are covered by a test - ninety test
references in all - two are partly covered, and eleven are not. The eleven
are named with the reason: the video rooms are not built, the confirmation
messages need a transport that does not exist, and seven of the eleven
non-functional gates are the work of the compliance review.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
