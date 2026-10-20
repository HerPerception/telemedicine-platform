# Booking and schedule management design

- **Feature:** `ENG-003` — implement appointment booking and clinician schedule management
- **Status:** Implemented and tested. The service layer is in-memory; the schema it depends on is
  [`db/schema.sql`](../db/schema.sql) (ENG-001) and has **not** been executed (no PostgreSQL server is
  available in the development environment).
- **Owner:** `OpenCode-20261019-3dafd2c8`

## 1. Acceptance criteria

The backlog item is: *"no double-booking; reschedule/cancel frees a slot; time-zone correctness."*

| Criterion | Where | Evidence |
| --- | --- | --- |
| No double-booking | `telemedicine/booking.py` — the check and the write happen under one lock; ENG-001's schema is the second line of defence | `tests/test_booking.py::BookingTestCase::test_a_slot_cannot_be_booked_twice`, `::test_only_one_of_two_racing_bookings_succeeds` |
| Reschedule frees a slot | `BookingService.reschedule` moves the appointment and releases the old slot | `::test_rescheduling_moves_the_appointment_and_frees_the_old_slot`, `::test_the_old_slot_can_be_booked_again_after_a_reschedule` |
| Cancel frees a slot | `BookingService.cancel` releases the slot and keeps the cancelled appointment | `::test_cancelling_frees_the_slot`, `::test_a_cancelled_slot_can_be_booked_again` |
| Time-zone correctness | `telemedicine/booking.py` — local times are resolved to UTC, gaps and overlaps are refused, comparisons are on instants | `tests/test_schedule.py::LocalTimeResolutionTest` |

## 2. The slot

A slot is a window in a practitioner's schedule that a patient can book.

| Property | Value |
| --- | --- |
| Authored in | the practitioner's local wall-clock time, with the IANA zone name |
| Stored as | a UTC instant (`starts_at`, `ends_at`), plus the zone name for rendering |
| Granularity | whole minutes |
| Length | 1 minute to 12 hours, matching the `CHECK` constraints in the schema |
| Overlap | two slots of the same practitioner may not overlap |

The slot table already existed (ENG-001); this feature implements the behaviour around it.

## 3. Time zones

`resolve_local_time(local, zone, fold=None)` is the only place a local time becomes an instant.

- **A local time in a daylight-saving *gap*** — the clocks jump forward, so the local time never
  happened. The call is refused. Booking a slot that does not exist would put the appointment at
  the wrong time, and the error would only surface later, in the patient's calendar.
- **A local time in a daylight-saving *overlap*** — the clocks fall back, so the local time happens
  twice. The call is refused unless the caller says which one it means (`fold=0` for the first,
  `fold=1` for the second). A slot that starts at 02:30 on the night the clocks change is a real
  decision, not a detail to guess.
- **Everything else** is resolved with the zone's offset for that date.

All comparisons — is a slot free, is it in the past, does it overlap another — are made on the UTC
instants, never on the rendered local strings. The zone is kept so that a user can be shown the
local time, and so that a later change of the practitioner's zone does not rewrite history.

`to_local_time(instant, zone)` renders an instant for display.

## 4. Booking

`BookingService.book(actor, slot_id, patient_user_id=None)`

- A **patient** books for themselves. Naming anybody else is refused.
- A **practitioner** books for a patient, and only in their own schedule: the slot must belong to
  the practitioner making the booking, and the patient must be one they treat.
- The slot must be free, and must start in the future.
- The appointment takes the slot's window exactly, which is what the schema's composite foreign key
  requires.

Every call is authorized against the rule table and audited, with the outcome recorded whether it
succeeded or was refused. A booked appointment is registered with the records service, so it is
visible to the read paths of ENG-002 and is covered by the treatment relationship that the
authorization rules use.

### 4.1 No double-booking, in three layers

1. **The service** checks that the slot has no active appointment, and performs the check and the
   write under one lock, so two callers racing for the same slot cannot both succeed.
2. **The schema** has a unique index over the *active* appointments of a slot
   (`appointment_active_slot_key`), so even a race that slips past the service lock cannot produce
   two active appointments on one slot.
3. **The schema** has a GiST exclusion constraint over each practitioner's slots, so two
   overlapping slots cannot exist in the first place, and therefore neither can two overlapping
   appointments.

The first layer gives a good error message; the second and third are the guarantee.

## 5. Rescheduling and cancelling

**Reschedule** moves the appointment to another slot:

- the new slot must be free, in the future, and belong to the **same practitioner** — the MVP keeps
  an appointment with the clinician who was booked, and changing clinician is a different operation
  (a cancellation and a new booking), not a reschedule;
- the old slot has no active appointment any more, so it is bookable again;
- the appointment keeps its identity, so its id, its audit trail and the link to the patient are
  preserved.

**Cancel** ends the appointment:

- the appointment is kept, with `status = 'cancelled'` and a cancellation reason, because clinical
  records are never deleted and the record of what was booked and released matters;
- the slot is released and can be booked again;
- the cancelled appointment **keeps its reference to the slot it occupied**, so the history of what
  was booked is not lost. This is why the schema's slot uniqueness had to change (§7).

The appointment state machine used here is `booked → cancelled`. The rest of it — `arrived`,
`fulfilled`, `noshow` — belongs to the consultation and prescription features.

## 6. Audit

| Action | Recorded when |
| --- | --- |
| `slot.create` | a practitioner opens a slot |
| `slot.close` | a practitioner closes a free slot |
| `appointment.book` | an appointment is booked, or a booking is refused |
| `appointment.reschedule` | an appointment is moved, or the move is refused |
| `appointment.cancel` | an appointment is cancelled, or the cancellation is refused |

The entries go into the tamper-evident log of ENG-002, so the history of who booked, moved and
released which window is a chain that cannot be quietly rewritten.

## 7. Amendments to earlier features

This feature amends three files owned by earlier features. All three are recorded in
`multi-agent-orchestrator/resolution.md`, and the schema amendment was made **before the schema had
ever been applied to a database**, so no migration is needed.

| File | Amendment | Why |
| --- | --- | --- |
| `db/schema.sql` | `appointment.slot_id` changed from `NOT NULL UNIQUE` to `NOT NULL`, with a partial unique index `appointment_active_slot_key` over `slot_id WHERE status <> 'cancelled'` | With a plain unique constraint, cancelling an appointment would leave its slot permanently unbookable, because the cancelled row would still hold the slot. The partial index keeps the reference on the cancelled appointment while letting the slot be booked again. |
| `docs/data-model.md`, `docs/fhir-mappings.md` | The invariants and the `Appointment.slot` note were updated to match | The documentation must not contradict the schema |
| `telemedicine/authorization.py` | `ResourceType.SLOT` added, and six rules added for booking, rescheduling, cancelling and slot management | The rule table of ENG-002 did not cover appointments being created or changed, or slots at all. The rules are fail-closed: a request that matches no rule is denied. |
| `telemedicine/records.py` | `Appointment` gained a `slot_id` field | The schema's `appointment.slot_id` column requires it, and the booking service needs it to release a slot |
| `tests/test_schema.py` | The slot uniqueness assertion now checks the partial index | The schema changed |

## 8. Known gaps

1. **No reminders or notifications.** A booked appointment does not tell the patient. The README
   asks for confirmations to both parties; ENG-003 records the booking in the audit log but sends
   nothing. A mail or SMS transport does not exist in the MVP, and the same gap is recorded for
   ENG-002.
2. **The lock is in-process.** The service uses a `threading.Lock`, which is correct for one
   process. Across several application instances, the database constraint is what prevents
   double-booking, and the service's error message may be a "no longer available" rather than a
   precise reason. That is the right trade-off, and it is recorded here.
3. **No recurring slots.** A practitioner opens slots one by one. A weekly template would be a
   separate feature, and it interacts with the slot overlap constraint.
4. **No waitlist, no cancellation policy, no notice period.** A patient may cancel at any time up
   to the appointment, and the slot is released immediately. Whether a practice wants a notice
   period is a policy question for the owner.
5. **Rescheduling to a different clinician is not supported** (§5). It is deliberately a
   cancel-and-rebook.
6. **The appointment lifecycle stops at `cancelled`.** `arrived`, `fulfilled` and `noshow` are set
   by the consultation and prescription features.
7. **Time zones are per practitioner.** A patient in another zone sees the appointment in the
   clinician's zone, rendered in their own; the MVP has one clinician, so this is simple by
   accident rather than by design.

## 9. What the later features need

- **ENG-004** (video rooms) needs the appointment window to admit the two parties; the booking
  service is the single source of that window.
- **ENG-005** (e-prescriptions) needs an encounter, which needs a consultation that has happened.
- **ENG-006** (FHIR API) needs the booking service to expose `Appointment` and `Slot` with the
  status values of the R4 `AppointmentStatus` and `SlotStatus` value sets, and to apply the same
  authorization to every write.
