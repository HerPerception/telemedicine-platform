"""Tests for the retention policy and the job that would apply it.

**The most important thing these tests say is that nothing is deleted.**
The policy file in the repository has both flags off, so the job reports and
changes nothing; and the half-enabled state — switched on, but not signed —
is refused outright.

The rest of the tests are about the machinery: what is past its period, what
happens to a record that is removed, and the thirty-day grace period in
between.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from telemedicine.errors import ValidationError
from telemedicine.retention import (
    DRAFT_WARNING,
    DEFAULT_POLICY_PATH,
    GRACE_PERIOD_DAYS,
    REFUSAL_DISABLED,
    REFUSAL_SIGNATURE_REQUIRED,
    RECORD_AUDIT_LOG,
    RECORD_CLINICAL,
    RECORD_PRESCRIPTION_DOCUMENT,
    DeletionAuditEntry,
    InMemoryRetentionStore,
    RetentionCandidate,
    RetentionPolicy,
    RetentionPolicyError,
    RetentionRefused,
    RetentionSource,
    TrashedRecord,
    find_candidates,
    hard_delete,
    load_policy,
    policy_table_markdown,
    restore,
    soft_delete,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def tomorrow_at(hour: int, minute: int = 0):
    """A moment in the future, in the practice's own local time.

    A slot in the past cannot be booked, so a test that books one must not
    use a fixed date: the wall clock moves, and a suite that stops passing at
    a particular hour is a suite that fails in the continuous integration.
    """
    from datetime import datetime, timedelta
    moment = datetime.now() + timedelta(days=1)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
NOTICE_PATH = REPO_ROOT / "docs" / "compliance" / "privacy-notice-draft.md"

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def write_policy(directory, name, **overrides):
    """A policy file in a temporary place, with the given values."""
    values = {
        "adult_outpatient_years": 5,
        "adult_inpatient_years": 7,
        "child_until_age": 21,
        "prescription_years": 10,
        "audit_log_years": 7,
        "enabled": "false",
        "legal_advisor_signed": "false",
    }
    values.update({key: str(value) for key, value in overrides.items()})
    path = Path(directory) / name
    path.write_text("\n".join(f"{key}: {value}" for key, value in values.items()) + "\n",
                    encoding="utf-8")
    return path


class ThePolicyFileTest(unittest.TestCase):
    """The file that decides whether anything is deleted."""

    def test_the_policy_in_the_repository_is_switched_off(self):
        policy = load_policy()
        self.assertFalse(policy.enabled)
        self.assertFalse(policy.legal_advisor_signed)
        self.assertFalse(policy.may_delete)

    def test_the_numbers_are_the_ones_the_task_asked_for(self):
        policy = load_policy()
        self.assertEqual(policy.adult_outpatient_years, 5)
        self.assertEqual(policy.adult_inpatient_years, 7)
        self.assertEqual(policy.child_until_age, 21)
        self.assertEqual(policy.prescription_years, 10)
        self.assertEqual(policy.audit_log_years, 7)

    def test_the_file_says_the_numbers_are_placeholders(self):
        text = DEFAULT_POLICY_PATH.read_text(encoding="utf-8")
        self.assertIn("TODO_LEGAL", text)
        self.assertIn("TEMPORARY placeholders", text)

    def test_a_switched_off_policy_refuses(self):
        with self.assertRaises(RetentionRefused) as caught:
            load_policy().check_may_delete()
        self.assertEqual(str(caught.exception), REFUSAL_DISABLED)

    def test_a_switched_on_policy_that_is_not_signed_refuses(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = write_policy(directory, "policy.yaml", enabled="true")
            policy = load_policy(path)
        with self.assertRaises(RetentionRefused) as caught:
            policy.check_may_delete()
        self.assertEqual(str(caught.exception), REFUSAL_SIGNATURE_REQUIRED)

    def test_a_signed_policy_may_delete(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = write_policy(directory, "policy.yaml", enabled="true",
                                legal_advisor_signed="true")
            policy = load_policy(path)
        self.assertTrue(policy.may_delete)
        policy.check_may_delete()

    def test_an_unknown_key_is_an_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = write_policy(directory, "policy.yaml")
            path.write_text(path.read_text() + "invented_key: 3\n", encoding="utf-8")
            with self.assertRaises(RetentionPolicyError) as caught:
                load_policy(path)
        self.assertIn("invented_key", str(caught.exception))

    def test_a_missing_key_is_an_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = write_policy(directory, "policy.yaml")
            path.write_text("enabled: false\n", encoding="utf-8")
            with self.assertRaises(RetentionPolicyError) as caught:
                load_policy(path)
        self.assertIn("missing", str(caught.exception))

    def test_a_value_of_the_wrong_type_is_an_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = write_policy(directory, "policy.yaml", adult_outpatient_years="five")
            with self.assertRaises(RetentionPolicyError) as caught:
                load_policy(path)
        self.assertIn("whole number", str(caught.exception))

    def test_a_file_that_is_not_there_is_an_error(self):
        with self.assertRaises(RetentionPolicyError):
            load_policy("/tmp/opencode/no-such-policy-file.yaml")

    def test_comments_are_ignored(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.yaml"
            path.write_text(
                "# a comment\n"
                "enabled: false   # another comment\n"
                "adult_outpatient_years: 5\n"
                "adult_inpatient_years: 7\n"
                "child_until_age: 21\n"
                "prescription_years: 10\n"
                "audit_log_years: 7\n"
                "legal_advisor_signed: false\n", encoding="utf-8")
            policy = load_policy(path)
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.child_until_age, 21)


class ThePeriodsTest(unittest.TestCase):
    """How long a record is kept."""

    def test_an_adult_record_is_kept_for_five_years(self):
        policy = load_policy()
        years = policy.clinical_years_for(date(1988, 4, 12), NOW)
        self.assertEqual(years, 5)

    def test_a_childs_record_is_kept_until_they_reach_twenty_one(self):
        policy = load_policy()
        # Ten years old at the last visit: kept until they are 21.
        years = policy.clinical_years_for(date(2016, 1, 1), NOW)
        self.assertEqual(years, 21 - 10)

    def test_a_child_who_is_already_twenty_one_is_kept_for_the_ordinary_period(self):
        policy = load_policy()
        years = policy.clinical_years_for(date(2005, 1, 1), NOW)
        self.assertEqual(years, 5)

    def test_a_record_with_no_birth_date_is_kept_for_the_ordinary_period(self):
        policy = load_policy()
        self.assertEqual(policy.clinical_years_for(None, NOW), 5)

    def test_the_expiry_is_measured_from_the_last_visit(self):
        policy = load_policy()
        last_visit = datetime(2020, 1, 1, tzinfo=timezone.utc)
        expires = policy.expiry_for(last_visit, 5)
        self.assertEqual(expires.year, 2025)


class FakeSource(RetentionSource):
    """Records for the job to look at."""

    def __init__(self, patients=None, encounters=None, prescriptions=None,
                 documents=None, audit=None):
        self._patients = patients or []
        self._encounters = encounters or []
        self._prescriptions = prescriptions or []
        self._documents = documents or []
        self._audit = audit or []

    def patients(self):
        return self._patients

    def encounters(self):
        return self._encounters

    def prescriptions(self):
        return self._prescriptions

    def prescription_documents(self):
        return self._documents

    def audit_entries(self):
        return self._audit


class FakePatient:
    def __init__(self, patient_id="patient-1", date_of_birth="1988-04-12"):
        self.patient_id = patient_id
        self.date_of_birth = date_of_birth


class FakeEncounter:
    def __init__(self, patient_id="patient-1", started_at=None):
        self.patient_id = patient_id
        self.started_at = started_at or datetime(2015, 1, 1, tzinfo=timezone.utc)


class FakeDocument:
    def __init__(self, document_id="document-1", created_at=None):
        self.document_id = document_id
        self.created_at = created_at or datetime(2010, 1, 1, tzinfo=timezone.utc)


class FakeAuditEntry:
    def __init__(self, sequence=1, occurred_at=None):
        self.sequence = sequence
        self.occurred_at = occurred_at or datetime(2010, 1, 1, tzinfo=timezone.utc)


class TheCandidatesTest(unittest.TestCase):
    """What is past its period."""

    def setUp(self):
        self.policy = load_policy()

    def test_a_patient_who_has_not_been_seen_for_years_is_a_candidate(self):
        source = FakeSource(patients=[FakePatient()],
                             encounters=[FakeEncounter()])
        candidates = find_candidates(source, self.policy, NOW)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].record_type, RECORD_CLINICAL)
        self.assertEqual(candidates[0].record_id, "patient-1")
        self.assertTrue(candidates[0].deletable)

    def test_a_patient_who_was_seen_recently_is_not(self):
        source = FakeSource(patients=[FakePatient()],
                             encounters=[FakeEncounter(
                                 started_at=datetime(2025, 1, 1, tzinfo=timezone.utc))])
        self.assertEqual(find_candidates(source, self.policy, NOW), [])

    def test_a_patient_with_no_visit_is_not_a_candidate(self):
        source = FakeSource(patients=[FakePatient()], encounters=[])
        self.assertEqual(find_candidates(source, self.policy, NOW), [])

    def test_a_childs_record_is_kept_for_longer(self):
        child = FakePatient(date_of_birth="2016-01-01")
        source = FakeSource(patients=[child],
                             encounters=[FakeEncounter(
                                 started_at=datetime(2018, 1, 1, tzinfo=timezone.utc))])
        # Kept until 2037, so not yet a candidate.
        self.assertEqual(find_candidates(source, self.policy, NOW), [])

    def test_the_audit_trail_is_reported_but_not_removed(self):
        source = FakeSource(audit=[FakeAuditEntry()])
        candidates = find_candidates(source, self.policy, NOW)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].record_type, RECORD_AUDIT_LOG)
        self.assertFalse(candidates[0].deletable)
        self.assertIn("hash chain", candidates[0].note)

    def test_a_prescription_document_is_reported_but_not_removed(self):
        source = FakeSource(documents=[FakeDocument()])
        candidates = find_candidates(source, self.policy, NOW)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].record_type, RECORD_PRESCRIPTION_DOCUMENT)
        self.assertFalse(candidates[0].deletable)
        self.assertIn("immutable", candidates[0].note)


class TheDeletionTest(unittest.TestCase):
    """What happens to a record that is removed."""

    def setUp(self):
        self.policy = RetentionPolicy(
            adult_outpatient_years=5, adult_inpatient_years=7, child_until_age=21,
            prescription_years=10, audit_log_years=7, enabled=True,
            legal_advisor_signed=True, source_path="policy.yaml")
        self.store = InMemoryRetentionStore()
        self.source = FakeSource(patients=[FakePatient()],
                                 encounters=[FakeEncounter()])
        self.candidates = [RetentionCandidate(
            record_type=RECORD_CLINICAL, record_id="patient-1",
            patient_id="patient-1",
            last_activity=datetime(2015, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            reason="no visit for 5 years")]

    def test_the_soft_delete_copies_the_record_into_the_trash(self):
        soft_delete(self.candidates, self.store, self.source, self.policy, NOW)
        trash = self.store.trash()
        self.assertEqual(len(trash), 1)
        self.assertEqual(trash[0].record_id, "patient-1")
        self.assertEqual(trash[0].deleted_at, NOW)
        self.assertEqual(trash[0].purge_after, NOW + timedelta(days=GRACE_PERIOD_DAYS))
        payload = json.loads(trash[0].payload)
        self.assertEqual(payload["record_id"], "patient-1")

    def test_the_soft_delete_marks_the_live_rows(self):
        soft_delete(self.candidates, self.store, self.source, self.policy, NOW)
        self.assertIn("clinical_record:patient-1", self.store.marked)

    def test_the_soft_delete_is_written_to_the_audit(self):
        soft_delete(self.candidates, self.store, self.source, self.policy, NOW)
        entries = self.store.deletion_audit()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].stage, "soft")
        self.assertEqual(entries[0].record_id, "patient-1")
        self.assertTrue(entries[0].reason)

    def test_nothing_is_removed_before_the_grace_period(self):
        soft_delete(self.candidates, self.store, self.source, self.policy, NOW)
        hard_delete(self.store, self.policy, NOW + timedelta(days=29))
        self.assertEqual(self.store.purged, [])
        self.assertEqual(len(self.store.trash()), 1)

    def test_the_record_is_removed_after_the_grace_period(self):
        soft_delete(self.candidates, self.store, self.source, self.policy, NOW)
        entries = hard_delete(self.store, self.policy, NOW + timedelta(days=31))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].stage, "hard")
        self.assertEqual(self.store.purged, ["clinical_record:patient-1"])
        self.assertEqual(self.store.trash(), [])

    def test_the_hard_delete_is_written_to_the_audit(self):
        soft_delete(self.candidates, self.store, self.source, self.policy, NOW)
        hard_delete(self.store, self.policy, NOW + timedelta(days=31))
        stages = [entry.stage for entry in self.store.deletion_audit()]
        self.assertEqual(stages, ["soft", "hard"])

    def test_a_record_can_be_put_back_while_it_still_can_be(self):
        soft_delete(self.candidates, self.store, self.source, self.policy, NOW)
        self.assertTrue(restore(self.store, RECORD_CLINICAL, "patient-1"))
        self.assertEqual(self.store.trash(), [])

    def test_a_switched_off_policy_removes_nothing(self):
        policy = RetentionPolicy(
            adult_outpatient_years=5, adult_inpatient_years=7, child_until_age=21,
            prescription_years=10, audit_log_years=7, enabled=False,
            legal_advisor_signed=False, source_path="policy.yaml")
        with self.assertRaises(RetentionRefused):
            soft_delete(self.candidates, self.store, self.source, policy, NOW)
        self.assertEqual(self.store.trash(), [])
        self.assertEqual(self.store.deletion_audit(), [])

    def test_a_policy_that_is_not_signed_removes_nothing(self):
        policy = RetentionPolicy(
            adult_outpatient_years=5, adult_inpatient_years=7, child_until_age=21,
            prescription_years=10, audit_log_years=7, enabled=True,
            legal_advisor_signed=False, source_path="policy.yaml")
        with self.assertRaises(RetentionRefused) as caught:
            soft_delete(self.candidates, self.store, self.source, policy, NOW)
        self.assertEqual(str(caught.exception), REFUSAL_SIGNATURE_REQUIRED)
        self.assertEqual(self.store.trash(), [])

    def test_the_audit_trail_is_not_removed(self):
        candidate = RetentionCandidate(
            record_type=RECORD_AUDIT_LOG, record_id="1", patient_id=None,
            last_activity=datetime(2010, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2017, 1, 1, tzinfo=timezone.utc),
            reason="written long ago", deletable=False)
        soft_delete([candidate], self.store, self.source, self.policy, NOW)
        self.assertEqual(self.store.trash(), [])


class TheCommandTest(unittest.TestCase):
    """The command line."""

    @classmethod
    def setUpClass(cls):
        path = REPO_ROOT / "scripts" / "retention.py"
        spec = importlib.util.spec_from_file_location("retention_cli", path)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def run_cli(self, *arguments):
        import contextlib
        import io
        out = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errors):
            status = self.script.main(list(arguments))
        return status, out.getvalue(), errors.getvalue()

    def test_the_dry_run_reports_and_changes_nothing(self):
        status, out, _errors = self.run_cli("check", "--dry-run")
        self.assertEqual(status, 0)
        self.assertIn("Would delete", out)

    def test_the_default_policy_deletes_nothing(self):
        status, out, _errors = self.run_cli("check")
        self.assertEqual(status, 0)
        self.assertIn("Would delete 0 records", out)

    def test_the_delete_command_refuses_a_switched_off_policy(self):
        status, _out, errors = self.run_cli("delete")
        self.assertEqual(status, 1)
        self.assertIn(REFUSAL_DISABLED, errors)

    def test_a_switched_on_policy_that_is_not_signed_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = write_policy(directory, "policy.yaml", enabled="true")
            status, _out, errors = self.run_cli("check", "--policy", str(path))
            self.assertEqual(status, 1)
            self.assertIn(REFUSAL_SIGNATURE_REQUIRED, errors)
            status, _out, errors = self.run_cli("delete", "--policy", str(path))
            self.assertEqual(status, 1)
            self.assertIn(REFUSAL_SIGNATURE_REQUIRED, errors)

    def test_a_policy_that_cannot_be_read_is_an_error(self):
        status, _out, errors = self.run_cli("check", "--policy", "/tmp/opencode/nope.yaml")
        self.assertEqual(status, 2)
        self.assertIn("could not be read", errors)


class TheDatabaseTest(unittest.TestCase):
    """The trash and the deletion audit, in PostgreSQL.

    These need a PostgreSQL server, and are skipped without one.
    """

    def setUp(self):
        from tests.test_persistence import _fresh_database
        self.database = _fresh_database("telemedicine_retention_test")
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        from telemedicine.persistence.retention_store import PostgresRetentionStore
        self.store = PostgresRetentionStore(self.database)

    def test_the_trash_round_trips(self):
        record = TrashedRecord(
            trash_id="11111111-1111-4111-8111-111111111111",
            record_type=RECORD_CLINICAL, record_id="patient-1",
            patient_id=None, payload=json.dumps({"record_id": "patient-1"}),
            deleted_at=NOW, purge_after=NOW + timedelta(days=GRACE_PERIOD_DAYS))
        self.store.add_trash(record)
        trash = self.store.trash()
        self.assertEqual(len(trash), 1)
        self.assertEqual(trash[0].record_id, "patient-1")
        self.assertEqual(trash[0].purge_after, NOW + timedelta(days=GRACE_PERIOD_DAYS))

        self.store.remove_trash(record.trash_id)
        self.assertEqual(self.store.trash(), [])

    def test_the_deletion_audit_is_written_and_read_back(self):
        entry = DeletionAuditEntry(
            entry_id="22222222-2222-4222-8222-222222222222",
            record_type=RECORD_CLINICAL, record_id="patient-1",
            patient_id=None, stage="soft", occurred_at=NOW,
            reason="no visit for 5 years", policy_source="policy.yaml")
        self.store.record_deletion(entry)
        entries = self.store.deletion_audit()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].stage, "soft")
        self.assertEqual(entries[0].reason, "no visit for 5 years")

    def test_the_deletion_audit_refuses_a_change(self):
        self.store.record_deletion(DeletionAuditEntry(
            entry_id="33333333-3333-4333-8333-333333333333",
            record_type=RECORD_CLINICAL, record_id="patient-1",
            patient_id=None, stage="soft", occurred_at=NOW,
            reason="no visit for 5 years", policy_source="policy.yaml"))
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE deletion_audit SET reason = 'changed'")
        self.assertIn("append-only", str(caught.exception))

    def test_the_deletion_audit_refuses_a_removal(self):
        self.store.record_deletion(DeletionAuditEntry(
            entry_id="44444444-4444-4444-8444-444444444444",
            record_type=RECORD_CLINICAL, record_id="patient-1",
            patient_id=None, stage="soft", occurred_at=NOW,
            reason="no visit for 5 years", policy_source="policy.yaml"))
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM deletion_audit")
        self.assertIn("append-only", str(caught.exception))

    def test_the_deletion_audit_refuses_to_be_truncated(self):
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("TRUNCATE deletion_audit")
        self.assertIn("append-only", str(caught.exception))


class TheClinicalRowsTest(unittest.TestCase):
    """A soft-deleted record stops being served."""

    def setUp(self):
        from tests.test_persistence import _fresh_database
        self.database = _fresh_database("telemedicine_retention_clinical_test")
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        self.ids = self._visit()

    def store(self):
        from telemedicine.persistence.clinical_store import PostgresClinicalRepository
        return PostgresClinicalRepository(self.database)

    def _visit(self):
        """A booked visit, an encounter, and the store they are in."""
        import uuid

        from telemedicine.auth import AuthService
        from telemedicine.booking import BookingService, SlotService
        from telemedicine.models import Role
        from telemedicine.records import PatientRecord, PractitionerRecord, RecordsService

        records = RecordsService(repository=self.store())
        slots = SlotService(repository=self.store())
        auth = AuthService(audit=records.audit, password_iterations=1000)
        patient_id = str(uuid.uuid4())
        practitioner_id = str(uuid.uuid4())
        patient_account = auth.register("ada@example.org", "a-long-passphrase",
                                        Role.PATIENT, record_id=patient_id)
        practitioner_account = auth.register("dr@example.org", "a-long-passphrase",
                                             Role.PRACTITIONER,
                                             record_id=practitioner_id)
        self.store().save_patient(PatientRecord(
            patient_id=patient_id, user_id=patient_account.user_id,
            display_name="Ada Nwosu", mrn="MRN-000123",
            family_name="Nwosu", given_names=("Ada",)))
        self.store().save_practitioner(PractitionerRecord(
            practitioner_id=practitioner_id, user_id=practitioner_account.user_id,
            display_name="Dr. Elena Ramirez", identifier="NPI 1234567893",
            family_name="Ramirez", given_names=("Elena",), credentials=("MD",)))
        booking = BookingService(slots, records=records, accounts=auth.users,
                                 audit=records.audit)
        slot = slots.create_slot(
            practitioner_account, practitioner_id=practitioner_id,
            local_start=tomorrow_at(14),
            local_end=tomorrow_at(14, 30), timezone_name="Europe/Berlin")
        appointment = booking.book(patient_account, slot.slot_id)
        records.create_encounter(practitioner_account, appointment.appointment_id,
                                 started_at=datetime(2026, 10, 21, 14, 0),
                                 ended_at=datetime(2026, 10, 21, 14, 25))
        return {"patient": patient_id, "practitioner": practitioner_id}

    def test_a_marked_record_is_not_served(self):
        store = self.store()
        patient_id = self.ids["patient"]
        self.assertIsNotNone(store.get_patient(patient_id))

        store.mark_deleted(RECORD_CLINICAL, patient_id, NOW)
        self.assertIsNone(store.get_patient(patient_id))
        self.assertEqual(store.list_patients(), [])
        self.assertEqual(store.list_encounters(), [])

    def test_a_purged_record_is_gone(self):
        store = self.store()
        patient_id = self.ids["patient"]
        store.mark_deleted(RECORD_CLINICAL, patient_id, NOW)
        removed = store.purge_deleted(RECORD_CLINICAL, patient_id)
        self.assertGreater(removed, 0)
        self.assertIsNone(store.get_patient(patient_id))


class ThePrivacyNoticeTest(unittest.TestCase):
    """The notice and the policy cannot drift apart."""

    @classmethod
    def setUpClass(cls):
        cls.text = NOTICE_PATH.read_text(encoding="utf-8")

    def test_the_notice_carries_the_draft_warning(self):
        self.assertIn(DRAFT_WARNING, self.text)

    def test_the_notice_has_the_table_the_policy_generates(self):
        policy = load_policy()
        self.assertIn(policy_table_markdown(policy), self.text)

    def test_the_notice_says_that_nothing_is_deleted_yet(self):
        self.assertIn("nothing is deleted", self.text)


if __name__ == "__main__":
    unittest.main()
