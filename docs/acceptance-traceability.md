# Acceptance criteria and their tests

- **Feature:** `QA-001` — automated tests covering each MVP acceptance criterion
- **Purpose:** one place that says, for every acceptance criterion of the MVP, whether it is covered
  by a test and by which one — and, where it is not, why not.
- **Enforced by:** `tests/test_acceptance_criteria.py`, which fails if a criterion is missing, if a
  covered criterion names a test that does not exist, if an uncovered criterion gives no reason,
  or if the CI workflow stops running the suite.

## Where the criteria come from

The acceptance criteria of the MVP are the ones in the README's "MVP scope" table, in the
non-functional gates it lists, and in the feature backlog. **The README in `main` is a two-line
stub** — the honest MVP README is DOC-001's work and is still uncommitted in the primary checkout —
so the criteria this document tracks are reproduced here, and this document is the source of truth
for the test that enforces it.

Two of the four capability criteria come from the README's MVP scope table, and the gates from its
non-functional list. Where a criterion cannot be covered yet, the row says so and why.

The gate rows refer to the compliance review of **OPS-001**,
[`reviews/compliance-review.md`](reviews/compliance-review.md), which is in the repository. The
finding numbers in those rows — PRIV-02, SEC-05 and so on — are that review's.

## How to read the table

| Column | Meaning |
| --- | --- |
| **Status** | `covered` — at least one deterministic test covers it. `partial` — part of it is covered and the rest cannot be yet. `not covered` — nothing covers it yet |
| **Test(s)** | `path::Class::test_name`, separated by `;`. Every reference is checked by the test, so a renamed or deleted test breaks this document |
| **Feature** | The feature that owns the criterion |
| **Note** | Required for `partial` and `not covered`: what is missing and why |

## The capabilities

| ID | Criterion | Status | Test(s) | Feature | Note |
| --- | --- | --- | --- | --- | --- |
| AC-BOOK-01 | Double-booking is impossible | covered | `tests/test_booking.py::BookingTestCase::test_a_slot_cannot_be_booked_twice`; `tests/test_booking.py::BookingTestCase::test_only_one_of_two_racing_bookings_succeeds`; `tests/test_schema.py::SchemaStructureTest::test_appointment_slot_is_unique_among_active_appointments`; `tests/test_schema.py::SchemaStructureTest::test_slots_cannot_overlap_for_one_practitioner` | ENG-003 | |
| AC-BOOK-02 | Slot availability is correct across time zones | covered | `tests/test_schedule.py::LocalTimeResolutionTest::test_a_local_time_resolves_to_the_right_utc_instant`; `tests/test_schedule.py::LocalTimeResolutionTest::test_winter_and_summer_use_different_offsets`; `tests/test_schedule.py::LocalTimeResolutionTest::test_the_same_instant_is_the_same_instant_in_every_zone`; `tests/test_schedule.py::LocalTimeResolutionTest::test_a_local_time_in_a_gap_does_not_exist_and_is_refused` | ENG-003 | |
| AC-BOOK-03 | Cancelling frees the slot | covered | `tests/test_booking.py::BookingTestCase::test_cancelling_frees_the_slot`; `tests/test_booking.py::BookingTestCase::test_a_cancelled_slot_can_be_booked_again`; `tests/test_booking.py::BookingTestCase::test_a_cancelled_appointment_keeps_its_slot_reference` | ENG-003 | |
| AC-BOOK-04 | Rescheduling frees the slot | covered | `tests/test_booking.py::BookingTestCase::test_rescheduling_moves_the_appointment_and_frees_the_old_slot`; `tests/test_booking.py::BookingTestCase::test_the_old_slot_can_be_booked_again_after_a_reschedule` | ENG-003 | |
| AC-BOOK-05 | Both parties receive a confirmation | not covered | — | ENG-003 | The MVP has no mail or SMS transport, so nothing can be sent yet. The booking is recorded in the audit log; the notification is part of the transport work that OPS-002 depends on |
| AC-BOOK-06 | A patient books only for themselves, and a clinician only in their own schedule | covered | `tests/test_booking.py::BookingTestCase::test_a_patient_cannot_book_for_somebody_else`; `tests/test_booking.py::BookingTestCase::test_a_practitioner_may_not_book_a_slot_of_another_practitioner`; `tests/test_booking.py::BookingTestCase::test_a_patient_may_not_cancel_another_patients_appointment` | ENG-003 | |
| AC-VIDEO-01 | Only the booked patient and clinician can join the consultation | not covered | — | ENG-004 | Not implemented. ENG-004 needs an external media service, which the environment does not have |
| AC-VIDEO-02 | The room is unavailable outside the appointment window | not covered | — | ENG-004 | Not implemented, for the same reason |
| AC-VIDEO-03 | A join failure surfaces a clear error and a retry path | not covered | — | ENG-004 | Not implemented, for the same reason |
| AC-RX-01 | Prescriptions are tied to the encounter and the patient | covered | `tests/test_prescriptions.py::IssuingTest::test_the_prescription_is_tied_to_the_encounter_and_the_patient`; `tests/test_prescriptions.py::IssuingTest::test_the_treating_clinician_can_issue`; `tests/test_schema.py::SchemaStructureTest::test_encounter_and_prescription_keep_their_parents_consistent` | ENG-005 | |
| AC-RX-02 | Only the treating clinician can issue a prescription | covered | `tests/test_prescriptions.py::IssuingTest::test_a_patient_cannot_issue_a_prescription`; `tests/test_prescriptions.py::IssuingTest::test_a_clinician_who_did_not_treat_the_patient_cannot_issue`; `tests/test_authorization.py::RecordsServiceAccessTest::test_another_clinician_may_not_issue_for_an_encounter_they_did_not_have` | ENG-005 | |
| AC-RX-03 | Every create and read of a prescription is audit-logged | covered | `tests/test_prescriptions.py::IssuingTest::test_issuing_is_audited`; `tests/test_prescriptions.py::IssuingTest::test_a_refused_issue_is_audited`; `tests/test_prescriptions.py::DownloadTest::test_downloading_is_audited_separately_from_reading`; `tests/test_prescriptions.py::DownloadTest::test_a_refused_download_is_audited` | ENG-005 | |
| AC-RX-04 | The document renders correctly when downloaded | covered | `tests/test_prescriptions.py::DocumentTest::test_the_document_renders_in_a_real_pdf_reader`; `tests/test_prescriptions.py::DocumentTest::test_the_document_is_a_pdf`; `tests/test_prescriptions.py::DocumentTest::test_the_document_states_the_prescription`; `tests/test_prescriptions.py::DownloadTest::test_the_patient_can_download_their_own_prescription` | ENG-005 | The rendering test needs poppler's `pdftotext` and is skipped without it; the other three do not |
| AC-RX-05 | The patient may read and download their own prescription, and nobody else may | covered | `tests/test_prescriptions.py::DownloadTest::test_the_patient_can_download_their_own_prescription`; `tests/test_prescriptions.py::DownloadTest::test_another_patient_cannot_download_the_prescription`; `tests/test_prescriptions.py::DownloadTest::test_another_clinician_cannot_download_the_prescription` | ENG-005 | |
| AC-RX-06 | A document that does not match its checksum is not served | covered | `tests/test_prescriptions.py::DocumentTest::test_a_tampered_document_is_detected`; `tests/test_prescriptions.py::DownloadTest::test_a_tampered_document_is_not_served` | ENG-005 | |
| AC-FHIR-01 | Patient, Practitioner, Appointment, Encounter and MedicationRequest are readable | covered | `tests/test_fhir_api.py::ReadTest::test_a_patient_reads_their_own_record`; `tests/test_fhir_api.py::ReadTest::test_the_appointment_is_readable_by_both_parties`; `tests/test_fhir_api.py::ReadTest::test_the_encounter_and_the_prescription_are_readable`; `tests/test_fhir_api.py::ReadTest::test_search_returns_a_bundle` | ENG-006 | |
| AC-FHIR-02 | The five resources are writable | covered | `tests/test_fhir_api.py::WriteTest::test_a_patient_updates_their_own_record`; `tests/test_fhir_api.py::WriteTest::test_a_patient_books_an_appointment`; `tests/test_fhir_api.py::WriteTest::test_the_treating_clinician_issues_a_prescription` | ENG-006 | |
| AC-FHIR-03 | Authentication and authorization are applied to every access | covered | `tests/test_fhir_api.py::AuthenticationTest::test_a_request_without_a_token_is_refused`; `tests/test_fhir_api.py::AuthenticationTest::test_a_revoked_token_is_refused`; `tests/test_fhir_api.py::ReadTest::test_a_patient_cannot_read_another_patients_record`; `tests/test_fhir_api.py::ReadTest::test_a_practitioner_cannot_read_an_unrelated_patient` | ENG-006 | |
| AC-FHIR-04 | Responses validate against FHIR R4 profiles | covered | `tests/test_fhir_serialization.py::SerializationTest::test_every_resource_satisfies_the_published_profile`; `tests/test_fhir_api.py::ReadTest::test_a_patient_reads_their_own_record`; `tests/test_fhir_examples.py::ExampleResourcesTest::test_all_examples_are_valid` | ENG-006 | |
| AC-FHIR-05 | Unauthorized access returns the correct error | covered | `tests/test_fhir_api.py::AuthenticationTest::test_a_request_without_a_token_is_refused`; `tests/test_fhir_api.py::ReadTest::test_an_unknown_id_is_not_found`; `tests/test_fhir_api.py::WriteTest::test_a_clinical_record_is_never_deleted`; `tests/test_fhir_api.py::WriteTest::test_booking_a_slot_twice_is_a_conflict` | ENG-006 | |
| AC-FHIR-06 | A clinical record is never deleted | covered | `tests/test_fhir_api.py::WriteTest::test_a_clinical_record_is_never_deleted`; `tests/test_schema.py::SchemaStructureTest::test_clinical_data_is_never_cascade_deleted`; `tests/test_auth_schema.py::AuthSchemaStructureTest::test_audit_log_has_no_delete_path_in_the_schema` | ENG-006 | |
| AC-SEC-01 | Both roles authenticate | covered | `tests/test_auth.py::AuthenticationTest::test_both_roles_authenticate`; `tests/test_auth.py::RegistrationTest::test_register_creates_an_account_for_each_role` | ENG-002 | |
| AC-SEC-02 | A session token is shown once and only its digest is stored | covered | `tests/test_auth.py::SessionTest::test_the_raw_token_is_never_stored`; `tests/test_auth.py::SessionTest::test_create_session_returns_a_usable_token`; `tests/test_auth_schema.py::AuthSchemaStructureTest::test_sessions_store_only_a_token_digest` | ENG-002 | |
| AC-SEC-03 | Access to records and prescriptions is role-scoped | covered | `tests/test_authorization.py::RecordsServiceAccessTest::test_a_patient_may_not_read_another_patients_record`; `tests/test_authorization.py::RecordsServiceAccessTest::test_a_practitioner_may_not_read_an_unrelated_patient`; `tests/test_authorization.py::AuthorizationRulesTest::test_an_unknown_role_action_pair_is_denied`; `tests/test_authorization.py::AuthorizationRulesTest::test_a_disabled_account_is_denied_everything` | ENG-002 | |
| AC-SEC-04 | Every access to a record or a prescription leaves an audit entry | covered | `tests/test_authorization.py::RecordsServiceAccessTest::test_every_read_of_a_record_leaves_an_audit_entry`; `tests/test_authorization.py::RecordsServiceAccessTest::test_prescription_creation_is_audited_against_the_encounter`; `tests/test_fhir_api.py::AuditTest::test_reading_through_the_api_is_audited`; `tests/test_fhir_api.py::AuditTest::test_a_refused_read_is_audited` | ENG-002 | |
| AC-SEC-05 | The audit log is tamper-evident | covered | `tests/test_audit.py::TamperDetectionTest::test_an_altered_entry_is_detected`; `tests/test_audit.py::TamperDetectionTest::test_a_deleted_entry_is_detected`; `tests/test_audit.py::TamperDetectionTest::test_appending_to_a_broken_log_is_refused`; `tests/test_audit.py::TamperDetectionTest::test_an_untouched_log_verifies` | ENG-002 | |
| AC-SEC-06 | A password is never stored in the clear | covered | `tests/test_auth.py::PasswordHashingTest::test_hash_is_not_the_password`; `tests/test_auth.py::PasswordHashingTest::test_same_password_gets_a_different_hash_each_time`; `tests/test_auth_schema.py::AuthSchemaStructureTest::test_user_account_stores_no_plaintext_password` | ENG-002 | |
| AC-DATA-01 | The clinical model is documented and mapped onto FHIR R4 | covered | `tests/test_fhir_examples.py::ExampleResourcesTest::test_all_examples_are_valid`; `tests/test_fhir_examples.py::ExampleResourcesTest::test_cross_references_resolve`; `tests/test_schema.py::SchemaStructureTest::test_all_six_tables_are_defined`; `tests/test_fhir_serialization.py::SerializationTest::test_every_resource_satisfies_the_published_profile` | ENG-001 | |
| AC-DATA-02 | The database refuses what the rules forbid | covered | `tests/test_schema.py::SchemaStructureTest::test_appointment_window_must_match_the_slot`; `tests/test_schema.py::SchemaStructureTest::test_cancelled_appointments_need_a_reason`; `tests/test_schema.py::SchemaStructureTest::test_status_columns_are_constrained_to_known_values`; `tests/test_auth_schema.py::AuthSchemaStructureTest::test_audit_log_is_append_only`; `tests/test_prescription_schema.py::PrescriptionSchemaTest::test_a_document_cannot_be_rewritten` | ENG-001 | |

## The non-functional gates

These are the README's release gates. They are not "acceptance criteria" of a feature, but they are
the conditions of a deployment, and the review of OPS-001 assessed them.

| ID | Gate | Status | Test(s) | Feature | Note |
| --- | --- | --- | --- | --- | --- |
| AC-GATE-01 | Privacy: consent capture | not covered | — | OPS-001 | There is no consent flow to test. PRIV-02 of the compliance review, and a blocker for sign-off |
| AC-GATE-02 | Privacy: minimum-necessary data access | partial | `tests/test_authorization.py::RecordsServiceAccessTest::test_a_patient_may_not_read_another_patients_record`; `tests/test_authorization.py::RecordsServiceAccessTest::test_a_practitioner_may_not_read_an_unrelated_patient` | OPS-001 | Access is scoped, but the API returns the whole patient record to anyone who may read it (PRIV-06) |
| AC-GATE-03 | Privacy: a documented retention policy | not covered | — | OPS-001 | There is no policy and no purge process (PRIV-03), and no test could exist until there is something to purge |
| AC-GATE-04 | Security: TLS in transit | not covered | — | OPS-001 | The server speaks plain HTTP (SEC-05); a deployment terminates TLS in front of it |
| AC-GATE-05 | Security: encryption at rest | not covered | — | OPS-001 | There is no storage yet, and the prescription documents are in memory (PRIV-05) |
| AC-GATE-06 | Security: strong authentication | partial | `tests/test_auth.py::AuthenticationTest::test_both_roles_authenticate`; `tests/test_auth.py::PasswordHashingTest::test_verify_accepts_the_right_password_and_rejects_others`; `tests/test_auth.py::SessionTest::test_an_expired_session_is_rejected`; `tests/test_auth.py::SessionTest::test_a_disabled_account_cannot_use_an_existing_session` | OPS-001 | Passwords, sessions and roles are covered; there is no lockout, no MFA and no breached-password screening (SEC-04, SEC-11, SEC-12) |
| AC-GATE-07 | Security: role-based authorization | covered | `tests/test_authorization.py::AuthorizationRulesTest::test_an_unknown_role_action_pair_is_denied`; `tests/test_authorization.py::AuthorizationRulesTest::test_a_disabled_account_is_denied_everything` | ENG-002 | The rules are explicit and fail closed |
| AC-GATE-08 | Auditability: tamper-evident logs | covered | `tests/test_audit.py::TamperDetectionTest::test_an_altered_entry_is_detected`; `tests/test_audit.py::TamperDetectionTest::test_a_deleted_entry_is_detected`; `tests/test_audit.py::AuditLogTest::test_entries_cannot_be_mutated` | ENG-002 | The chain is tamper-evident in the process; it is not durable across a restart, and it is not anchored outside the store (SEC-06, SEC-07) |
| AC-GATE-09 | Reliability: backups, restore testing and a recovery procedure | not covered | — | OPS-002 | There is no database to back up (SEC-06) |
| AC-GATE-10 | Accessibility: WCAG 2.1 AA for the booking and consultation flows | not covered | — | OPS-001 | There is no user interface, so the gate cannot be assessed (A11Y-01) |
| AC-GATE-11 | Regulatory: the rules of the target jurisdiction | not covered | — | OPS-001 | The jurisdiction is not established, so the question cannot be asked yet (REG-01) — the one critical finding of the review |

## What is left, and who owns it

| Owner | Criteria still open |
| --- | --- |
| ENG-004 | AC-VIDEO-01, AC-VIDEO-02, AC-VIDEO-03 |
| ENG-003 | AC-BOOK-05 (the notification needs a transport) |
| OPS-001 | AC-GATE-01, AC-GATE-03, AC-GATE-04, AC-GATE-05, AC-GATE-10, AC-GATE-11, and the partial ones |
| OPS-002 | AC-GATE-09 |

The criteria are deliberately not all covered, and the ones that are not are named with the reason.
That is the point of this document: a criterion that is quietly not tested is the thing that reaches
a patient untested.
