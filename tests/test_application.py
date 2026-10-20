"""The application, assembled, and the whole stack over HTTP.

The end-to-end test is the one that matters: it builds the application the
way a deployment does, runs it over a real socket against a real database,
and then does what a patient does — register, sign in, book, and read the
booking back through the FHIR API.

The tests that need a database are skipped without one.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

from tests.test_persistence import _fresh_database

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class SettingsTest(unittest.TestCase):
    def test_the_settings_come_from_the_environment(self):
        from telemedicine.config import Settings
        settings = Settings.from_environment({
            "TELEMEDICINE_DATABASE_URL": "postgresql://localhost/telemedicine",
            "TELEMEDICINE_HOST": "0.0.0.0",
            "TELEMEDICINE_PORT": "9000",
        })
        self.assertTrue(settings.has_database)
        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 9000)

    def test_without_a_database_the_records_stay_in_memory(self):
        from telemedicine.config import Settings
        settings = Settings.from_environment({})
        self.assertFalse(settings.has_database)
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8080)

    def test_the_description_does_not_leak_the_connection_string(self):
        from telemedicine.config import Settings
        settings = Settings.from_environment({
            "TELEMEDICINE_DATABASE_URL": "postgresql://user:secret@localhost/telemedicine"})
        self.assertNotIn("secret", settings.describe())


class WiringTest(unittest.TestCase):
    """The application assembles, with and without a database."""

    def test_it_assembles_without_a_database(self):
        from telemedicine.application import build_application
        from telemedicine.config import Settings
        application = build_application(Settings())
        self.assertIsNone(application.database)
        self.assertIsNotNone(application.fhir)
        self.assertIsNotNone(application.video_api)
        # The router carries both surfaces.
        self.assertEqual(set(application.http.applications), {"/fhir", "/video"})

    def test_it_assembles_with_a_database(self):
        from telemedicine.application import build_application
        from telemedicine.config import Settings
        from telemedicine.persistence.audit_store import PostgresAuditLog
        from telemedicine.persistence.clinical_store import PostgresClinicalRepository
        from telemedicine.persistence.lockout import PostgresLockoutStore

        database = _fresh_database("telemedicine_wiring_test")
        if database is None:
            self.skipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        application = build_application(Settings(database_url=_dsn()))
        self.assertIsInstance(application.audit, PostgresAuditLog)
        self.assertIsInstance(application.records.repository, PostgresClinicalRepository)
        self.assertIsInstance(application.auth.lockout, PostgresLockoutStore)


def _dsn() -> str:
    import os
    return os.environ["TELEMEDICINE_TEST_DSN"]


class EndToEndTest(unittest.TestCase):
    """The whole stack, over a socket, against a database."""

    def setUp(self):
        database = _fresh_database("telemedicine_end_to_end_test")
        if database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        self.database = database

        from telemedicine.application import build_application
        from telemedicine.config import Settings
        from telemedicine.fhir.server import make_server

        self.application = build_application(Settings(database_url=_dsn()))
        self.server = make_server(self.application.http, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    # -- helpers -----------------------------------------------------------

    def request(self, method, path, token=None, body=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, data=data, timeout=15) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def register(self, email, role, record_id):
        from telemedicine.models import Role
        account = self.application.auth.register(
            email, "a-long-passphrase", role, record_id=record_id)
        token, _session = self.application.auth.create_session(account)
        return account, token

    def add_patient_and_practitioner(self):
        from telemedicine.models import Role
        from telemedicine.records import PatientRecord, PractitionerRecord
        patient_id = str(uuid.uuid4())
        practitioner_id = str(uuid.uuid4())
        patient_account, patient_token = self.register(
            f"ada-{patient_id[:8]}@example.org", Role.PATIENT, patient_id)
        practitioner_account, practitioner_token = self.register(
            f"dr-{practitioner_id[:8]}@example.org", Role.PRACTITIONER, practitioner_id)
        self.application.records.add_patient(PatientRecord(
            patient_id=patient_id, user_id=patient_account.user_id,
            display_name="Ada Nwosu Okonkwo", family_name="Okonkwo",
            given_names=("Ada", "Nwosu"), mrn="MRN-" + patient_id[:8]))
        self.application.records.add_practitioner(PractitionerRecord(
            practitioner_id=practitioner_id, user_id=practitioner_account.user_id,
            display_name="Dr. Elena Ramirez", family_name="Ramirez",
            given_names=("Elena",), credentials=("MD",),
            identifier="NPI" + practitioner_id[:8],
            specialty="General Practice", license_number="MD-2019-4471"))
        return patient_id, practitioner_id, patient_token, practitioner_token

    # -- the test ----------------------------------------------------------

    def test_a_patient_books_and_reads_the_booking_back(self):
        from datetime import datetime as dt

        patient_id, practitioner_id, patient_token, practitioner_token = \
            self.add_patient_and_practitioner()

        # The clinician opens a slot, in their own local time.
        slot = self.application.slots.create_slot(
            self.application.auth.users.get_by_email(f"dr-{practitioner_id[:8]}@example.org"),
            practitioner_id=practitioner_id,
            local_start=dt(2026, 10, 21, 16, 0), local_end=dt(2026, 10, 21, 16, 30),
            timezone_name="Europe/Berlin")

        # The patient books it, through the FHIR API.
        body = {
            "resourceType": "Appointment",
            "status": "booked",
            "slot": [{"reference": f"Slot/{slot.slot_id}"}],
            "participant": [
                {"actor": {"reference": f"Patient/{patient_id}"}, "status": "accepted"},
                {"actor": {"reference": f"Practitioner/{practitioner_id}"},
                 "status": "accepted"},
            ],
        }
        status, created = self.request("POST", "/fhir/Appointment", patient_token, body)
        self.assertEqual(status, 201, created)
        self.assertEqual(created["resourceType"], "Appointment")
        self.assertEqual(len(created["participant"]), 2)

        # The booking is read back, and it is the same booking.
        status, read = self.request("GET", f"/fhir/Appointment/{created['id']}",
                                    patient_token)
        self.assertEqual(status, 200)
        self.assertEqual(read["id"], created["id"])
        self.assertEqual(read["start"], "2026-10-21T14:00:00Z")
        self.assertEqual(read["minutesDuration"], 30)

        # And it is in the database, not in the memory of the process.
        stored = self.application.records.get_appointment(created["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.patient_user_id,
                         self.application.auth.users.get_by_email(f"ada-{patient_id[:8]}@example.org").user_id)

        # The clinician sees it too.
        status, _read = self.request("GET", f"/fhir/Appointment/{created['id']}",
                                     practitioner_token)
        self.assertEqual(status, 200)

        # The audit trail has the whole visit.
        entries = self.application.audit.entries_for_resource("appointment", created["id"])
        self.assertTrue(entries)
        self.assertTrue(self.application.audit.verify_chain())

    def test_a_patient_cannot_read_another_patients_booking(self):
        patient_id, practitioner_id, patient_token, _practitioner_token = \
            self.add_patient_and_practitioner()
        from telemedicine.models import Role
        other_account, other_token = self.register(
            f"other-{uuid.uuid4().hex[:8]}@example.org", Role.PATIENT, str(uuid.uuid4()))

        # The clinician opens a slot and books it for the first patient.
        from datetime import datetime as dt
        slot = self.application.slots.create_slot(
            self.application.auth.users.get_by_email(f"dr-{practitioner_id[:8]}@example.org"),
            practitioner_id=practitioner_id,
            local_start=dt(2026, 10, 21, 16, 0), local_end=dt(2026, 10, 21, 16, 30),
            timezone_name="Europe/Berlin")
        appointment = self.application.booking.book(
            self.application.auth.users.get_by_email(f"ada-{patient_id[:8]}@example.org"), slot.slot_id)

        status, body = self.request("GET", f"/fhir/Appointment/{appointment.appointment_id}",
                                    other_token)
        self.assertEqual(status, 403)
        self.assertEqual(body["issue"][0]["code"], "forbidden")

    def test_an_unauthenticated_request_is_refused(self):
        status, body = self.request("GET", "/fhir/Patient/patient-1")
        self.assertEqual(status, 401)
        self.assertEqual(body["issue"][0]["code"], "login")


if __name__ == "__main__":
    unittest.main()
