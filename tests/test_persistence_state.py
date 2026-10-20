"""Tests for the accounts, the sessions and the documents in the database.

These need a PostgreSQL server. They are skipped when there is none, so
that the suite still runs on a machine without a database — and they are
run in the continuous integration, which has one.

The connection string comes from ``TELEMEDICINE_TEST_DSN``:

    TELEMEDICINE_TEST_DSN="postgresql://postgres@localhost/postgres" \\
        python3 -m unittest tests.test_persistence_state -v

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_persistence import _fresh_database

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class StateTestCase(unittest.TestCase):
    """A database of its own for every test."""

    database_name = "telemedicine_state_test"

    def setUp(self):
        self.database = _fresh_database(self.database_name)
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        self.database.apply_schema()

    def auth_service(self):
        """An authentication service backed by the database."""
        from telemedicine.auth import AuthService
        from telemedicine.persistence.account_store import (
            PostgresSessionStore,
            PostgresUserRepository,
        )
        from telemedicine.persistence.audit_store import PostgresAuditLog
        return AuthService(
            users=PostgresUserRepository(self.database),
            sessions=PostgresSessionStore(self.database),
            audit=PostgresAuditLog(self.database),
            password_iterations=1000,
        )


class AccountTest(StateTestCase):
    """The accounts are shared between the instances of the application."""

    def test_an_account_is_stored_and_read_back(self):
        from telemedicine.models import Role
        service = self.auth_service()
        account = service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-1")
        self.assertEqual(len(service.users), 1)

        # A new service, a new repository, the same database.
        other = self.auth_service()
        found = other.users.get_by_email("ada@example.org")
        self.assertIsNotNone(found)
        self.assertEqual(found.user_id, account.user_id)
        self.assertEqual(found.role, Role.PATIENT)
        self.assertEqual(found.record_id, "patient-1")
        self.assertFalse(found.disabled)

    def test_an_account_is_found_by_its_id_too(self):
        from telemedicine.models import Role
        service = self.auth_service()
        account = service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-1")
        other = self.auth_service()
        self.assertEqual(other.users.get_by_id(account.user_id).email, "ada@example.org")

    def test_a_password_hashed_in_one_instance_verifies_in_another(self):
        from telemedicine.models import Role
        service = self.auth_service()
        service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                         record_id="patient-1")
        other = self.auth_service()
        account = other.authenticate("ada@example.org", "a-long-passphrase")
        self.assertEqual(account.email, "ada@example.org")

    def test_the_email_is_matched_without_regard_to_case(self):
        from telemedicine.models import Role
        service = self.auth_service()
        service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                         record_id="patient-1")
        other = self.auth_service()
        self.assertIsNotNone(other.users.get_by_email("ADA@example.org"))


class SessionTest(StateTestCase):
    """A session issued on one instance works on the others."""

    def test_a_session_is_accepted_by_another_instance(self):
        from telemedicine.models import Role
        service = self.auth_service()
        account = service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-1")
        token, _session = service.create_session(account)

        # The request landed on a different instance.
        other = self.auth_service()
        accepted = other.authenticate_session(token)
        self.assertEqual(accepted.user_id, account.user_id)

    def test_a_revoked_session_is_refused_by_another_instance(self):
        from telemedicine.errors import AuthenticationError
        from telemedicine.models import Role
        service = self.auth_service()
        account = service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-1")
        token, _session = service.create_session(account)
        service.revoke_session(token)

        other = self.auth_service()
        with self.assertRaises(AuthenticationError):
            other.authenticate_session(token)

    def test_an_expired_session_is_refused(self):
        from telemedicine.auth import AuthService
        from telemedicine.errors import AuthenticationError
        from telemedicine.models import Role
        from telemedicine.persistence.account_store import (
            PostgresSessionStore,
            PostgresUserRepository,
        )
        from telemedicine.persistence.audit_store import PostgresAuditLog
        service = AuthService(
            users=PostgresUserRepository(self.database),
            sessions=PostgresSessionStore(self.database),
            audit=PostgresAuditLog(self.database),
            password_iterations=1000,
            session_ttl=timedelta(minutes=1),
            clock=lambda: NOW,
        )
        account = service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-1")
        token, _session = service.create_session(account)
        other = AuthService(
            users=PostgresUserRepository(self.database),
            sessions=PostgresSessionStore(self.database),
            audit=PostgresAuditLog(self.database),
            password_iterations=1000,
            session_ttl=timedelta(minutes=1),
            clock=lambda: NOW + timedelta(minutes=2),
        )
        with self.assertRaises(AuthenticationError):
            other.authenticate_session(token)

    def test_a_password_change_ends_the_sessions_of_the_account(self):
        from telemedicine.models import Role
        service = self.auth_service()
        account = service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-1")
        token, _session = service.create_session(account)
        service.set_password(account, "a-long-passphrase", "a-new-long-passphrase")

        other = self.auth_service()
        from telemedicine.errors import AuthenticationError
        with self.assertRaises(AuthenticationError):
            other.authenticate_session(token)

    def test_the_token_is_never_stored_in_the_clear(self):
        from telemedicine.models import Role
        service = self.auth_service()
        account = service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-1")
        token, _session = service.create_session(account)
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT token_hash FROM auth_session")
                stored = [row[0] for row in cursor.fetchall()]
        self.assertTrue(stored)
        self.assertNotIn(token, stored)
        for digest in stored:
            self.assertEqual(len(digest), 64)


class DocumentTest(StateTestCase):
    """The prescription document is durable, and it cannot be changed."""

    def _clinical_chain(self):
        """Write a patient, a practitioner, an appointment, an encounter and a
        prescription, in the order the foreign keys demand.

        It is more than the document test needs, and it is worth having: it
        proves the whole clinical chain can be written to the database, with
        every relationship the schema declares.
        """
        patient_id = str(uuid.uuid4())
        practitioner_id = str(uuid.uuid4())
        slot_id = str(uuid.uuid4())
        appointment_id = str(uuid.uuid4())
        encounter_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO patient (id, mrn, family_name, given_names, gender)"
                " VALUES (%s, %s, %s, %s, %s)",
                (patient_id, "MRN-" + patient_id[:8], "Okonkwo", ["Ada"], "unknown"))
            cursor.execute(
                "INSERT INTO practitioner (id, family_name, given_names, gender)"
                " VALUES (%s, %s, %s, %s)",
                (practitioner_id, "Ramirez", ["Elena"], "female"))
            cursor.execute(
                "INSERT INTO schedule_slot (id, practitioner_id, starts_at, ends_at, timezone)"
                " VALUES (%s, %s, %s, %s, %s)",
                (slot_id, practitioner_id, NOW, NOW + timedelta(minutes=30), "Europe/Berlin"))
            cursor.execute(
                "INSERT INTO appointment (id, patient_id, practitioner_id, slot_id, status,"
                " starts_at, ends_at, duration_minutes)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (appointment_id, patient_id, practitioner_id, slot_id, "booked", NOW,
                 NOW + timedelta(minutes=30), 30))
            cursor.execute(
                "INSERT INTO encounter (id, appointment_id, patient_id, practitioner_id,"
                " status, started_at, ended_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (encounter_id, appointment_id, patient_id, practitioner_id, "finished", NOW,
                 NOW + timedelta(minutes=25)))
            cursor.execute(
                "INSERT INTO medication_request (id, encounter_id, patient_id, prescriber_id,"
                " medication_system, medication_code, medication_display, dosage_text,"
                " status, authored_on) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (request_id, encounter_id, patient_id, practitioner_id,
                 "https://telemedicine.example.org/CodeSystem/medication", "AMOX-500-CAP",
                 "Amoxicillin 500 mg capsule", "One capsule three times a day", "active", NOW))
        return request_id

    def _document(self, medication_request_id=None):
        from telemedicine.prescriptions import PrescriptionDocument
        import hashlib
        body = b"%PDF-1.4 fake"
        return PrescriptionDocument(
            document_id=str(uuid.uuid4()),
            medication_request_id=medication_request_id or str(uuid.uuid4()),
            content_type="application/pdf",
            body=body,
            checksum=hashlib.sha256(body).hexdigest(),
            created_at=NOW,
        )

    def test_a_document_is_stored_and_read_back(self):
        from telemedicine.persistence.document_store import PostgresDocumentStore
        store = PostgresDocumentStore(self.database)
        document = self._document(self._clinical_chain())
        store.put(document)

        found = store.get_for_request(document.medication_request_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.body, document.body)
        self.assertEqual(found.checksum, document.checksum)
        self.assertTrue(found.checksum_matches())

    def test_a_document_survives_a_restart(self):
        from telemedicine.persistence.document_store import PostgresDocumentStore
        store = PostgresDocumentStore(self.database)
        document = self._document(self._clinical_chain())
        store.put(document)

        reopened = PostgresDocumentStore(self.database)
        found = reopened.get_for_request(document.medication_request_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.body, document.body)

    def test_a_document_cannot_be_changed(self):
        from telemedicine.persistence.document_store import PostgresDocumentStore
        store = PostgresDocumentStore(self.database)
        document = self._document(self._clinical_chain())
        store.put(document)
        with self.assertRaises(Exception):
            with self.database.transaction() as cursor:
                cursor.execute("UPDATE prescription_document SET body = %s WHERE id = %s",
                               (b"tampered", document.document_id))

    def test_a_document_cannot_be_deleted(self):
        # A prescription that has been printed and handed to a pharmacy must
        # not be able to disappear.
        from telemedicine.persistence.document_store import PostgresDocumentStore
        store = PostgresDocumentStore(self.database)
        document = self._document(self._clinical_chain())
        store.put(document)
        with self.assertRaises(Exception):
            with self.database.transaction() as cursor:
                cursor.execute("DELETE FROM prescription_document WHERE id = %s",
                               (document.document_id,))

    def test_a_prescription_has_one_document(self):
        from telemedicine.persistence.document_store import PostgresDocumentStore
        store = PostgresDocumentStore(self.database)
        request_id = self._clinical_chain()
        document = self._document(request_id)
        store.put(document)
        second = self._document(request_id)
        second = type(second)(**{**second.__dict__, "medication_request_id":
                                  document.medication_request_id})
        with self.assertRaises(Exception):
            store.put(second)


if __name__ == "__main__":
    unittest.main()
