# ENG-002: authentication, role-scoped authorization and an audit log

Adds the security layer the MVP needs before any patient data exists.

* telemedicine/auth.py - registration, password authentication and session
  lifecycle for both roles. Passwords are stored as PBKDF2-HMAC-SHA256
  hashes with a per-password salt; session tokens are shown once and only
  their SHA-256 digest is stored; sessions expire and can be revoked. Every
  login attempt is audited, and a failed login for an unknown account
  produces the same error as a wrong password so accounts cannot be
  enumerated.
* telemedicine/authorization.py - an explicit rule table plus a per-record
  scope. A patient may read their own records; a practitioner may read a
  patient only when an appointment or an encounter makes them that
  patient's clinician; only the treating clinician may issue a
  prescription. Anything not in the table is denied.
* telemedicine/audit.py - an append-only, tamper-evident log. Each entry
  carries the hash of the entry before it, and the log refuses to extend a
  chain that is already broken.
* telemedicine/records.py - the service layer: every read of a record and
  every prescription operation is authorized and then audited, with the
  outcome, allowed or refused.
* db/auth_schema.sql - PostgreSQL DDL for accounts, sessions and the audit
  log, with triggers that reject UPDATE, DELETE and TRUNCATE on the log.
* docs/auth-design.md - the design, the mapping to the README's compliance
  gates, and the gaps that remain (no lockout, no password reset, no
  retention policy).

Standard library only. Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

The DDL has not been executed: no PostgreSQL server was available in the
development environment.

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
