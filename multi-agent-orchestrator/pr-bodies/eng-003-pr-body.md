# ENG-003: appointment booking, schedule management and time-zone rules

Implements the booking half of the MVP: a practitioner opens slots in their
schedule, a patient books one, and both can reschedule or cancel.

* telemedicine/booking.py - SlotService and BookingService. A slot is
  authored in the practitioner's local wall-clock time and stored as a UTC
  instant with its IANA zone alongside. Local times that do not exist (a
  daylight-saving gap) or that happen twice (an overlap) are refused
  rather than silently shifted, and every comparison is made on the
  instants. Booking, rescheduling and cancelling are authorized against
  the rule table and audited, allowed or refused.
* docs/booking-design.md - the design, the time-zone policy, the three
  layers that prevent double-booking, and the gaps that remain.
* tests/test_booking.py, tests/test_schedule.py - the suites.

Three amendments to earlier features, recorded in the design document and
in the coordination log:

* db/schema.sql - appointment.slot_id changes from NOT NULL UNIQUE to
  NOT NULL, with a partial unique index over the active appointments of a
  slot. With a plain unique constraint, cancelling an appointment would
  leave its slot permanently unbookable, because the cancelled row would
  still hold the slot. The schema was amended before it had ever been
  applied to a database, so no migration is needed.
* telemedicine/authorization.py - ResourceType.SLOT and six rules for
  booking, rescheduling, cancelling and slot management. The rules are
  fail-closed: a request matching no rule is denied.
* telemedicine/records.py - Appointment gains the slot_id the schema
  requires, so that a slot can be released.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

The DDL has not been executed: no PostgreSQL server was available in the
development environment.

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
