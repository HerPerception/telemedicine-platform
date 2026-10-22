# OPS-001: privacy, security, accessibility and regulatory review

The MVP handles health data, and the README makes six compliance gates
release conditions. This reviews the whole feature set against them and
records what is still open.

* docs/reviews/compliance-review.md - the review. Thirty-seven findings
  across privacy, security, accessibility and regulation, each with the
  evidence it rests on, a severity, and a remediation. The verdict is not
  signed off: no real patient data until the conditions in section 8 are
  met, and the conditions are listed.

The one critical finding is REG-01: the jurisdiction is not established, so
none of the other regulatory questions can be answered. Two findings are
high and block sign-off on their own: no consent is captured, and nothing
is ever deleted with no retention policy behind it.

Four findings were cheap and safe to close, and are closed here:

* SEC-01 - the login returned immediately for an unknown account and only
  ran the PBKDF2 verification for a known one, so the response time said
  which addresses were registered. The unknown path now verifies against a
  decoy hash and costs the same.
* SEC-02 - a password change left every session issued under the old
  password alive. It now ends them all, and says so in the audit entry.
* SEC-03 - a refusal explained itself in the response, which told an
  unauthorised caller how the rule works. The reason stays in the audit log
  and the response says only what happened.
* PRIV-01 - a response holding a patient's record could be cached by an
  intermediary. Every response now carries Cache-Control: no-store.

Each of the four has a test in tests/test_compliance_remediations.py.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
