"""Tests for the clinical records in the database.

These need a PostgreSQL server. They are skipped when there is none, so
that the suite still runs on a machine without a database — and they are
run in the continuous integration, which has one.

The connection string comes from ``TELEMEDICINE_TEST_DSN``:

    TELEMEDICINE_TEST_DSN="postgresql://postgres@localhost/postgres" \\
        python3 -m unittest tests.test_persistence_clinical -v

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_persistence import _fresh_database

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class ClinicalTestCase(unittest.TestCase):
    """A database of its own for every test."""

    database_name = "telemedicine_clinical_test"

    def setUp(self):
        self.database = _fresh_database(self.database_name)
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        self.database.apply_schema()
        self.store = self.make_store()

    def make_store(self):
        from telemedicine.persistence.clinical_store import PostgresClinicalRepository
        return PostgresClinicalRepository(self.database)

    def make_records(self, store=None):
        from telemedicine.records import RecordsService
        return RecordsService(repository=store if store is not None else self.store)

    def make_slots(self, store=None):
        from telemedicine.booking import SlotService
        return SlotService(repository=store if store is not None else self.store)

    def patient(self, user_id=None, patient_id=None):
        from telemedicine.records import PatientRecord
        return PatientRecord(
            patient_id=patient_id or str(uuid.uuid4()),
            user_id=user_id or str(uuid.uuid4()),
            display_name="Ada Nwosu Okonkwo",
            date_of_birth="1988-04-12",
            mrn="MRN-000123",
            family_name="Okonkwo",
            given_names=("Ada", "Nwosu"),
            gender="unknown",
            phone="+1-555-0100",
            email="ada.okonkwo@example.com",
            address_line=("12 Harbour Street",),
            address_city="Boston",
            address_region="MA",
            address_postal_code="02110",
            address_country="US",
        )

    def practitioner(self, user_id=None, practitioner_id=None):
        from telemedicine.records import PractitionerRecord
        return PractitionerRecord(
            practitioner_id=practitioner_id or str(uuid.uuid4()),
            user_id=user_id or str(uuid.uuid4()),
            display_name="Dr. Elena Ramirez",
            identifier="1234567893",
            specialty="General Practice",
            family_name="Ramirez",
            given_names=("Elena",),
            credentials=("MD",),
            gender="female",
            license_number="MD-2019-4471",
            license_region="Massachusetts",
        )


class RecordTest(ClinicalTestCase):
    def test_a_patient_round_trips(self):
        patient = self.patient()
        self.store.save_patient(patient)
        found = self.store.get_patient(patient.patient_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.mrn, patient.mrn)
        self.assertEqual(found.family_name, "Okonkwo")
        self.assertEqual(found.given_names, ("Ada", "Nwosu"))
        self.assertEqual(found.gender, "unknown")
        self.assertEqual(found.phone, "+1-555-0100")
        self.assertEqual(found.address_city, "Boston")
        self.assertEqual(found.user_id, patient.user_id)

    def test_a_practitioner_round_trips(self):
        practitioner = self.practitioner()
        self.store.save_practitioner(practitioner)
        found = self.store.get_practitioner(practitioner.practitioner_id)
        self.assertEqual(found.identifier, "1234567893")
        self.assertEqual(found.credentials, ("MD",))
        self.assertEqual(found.license_number, "MD-2019-4471")
        self.assertEqual(found.user_id, practitioner.user_id)

    def test_the_records_survive_a_restart(self):
        patient = self.patient()
        self.store.save_patient(patient)
        # A new store is a new process as far as the data is concerned.
        reopened = self.make_store()
        self.assertIsNotNone(reopened.get_patient(patient.patient_id))
        self.assertEqual(len(reopened.list_patients()), 1)

    def test_two_services_share_the_records(self):
        patient = self.patient()
        self.records = self.make_records()
        self.records.add_patient(patient)
        other = self.make_records()
        self.assertEqual(len(other.list_patients()), 1)
        self.assertEqual(other.patient_record(patient.patient_id).mrn, "MRN-000123")


class TreatmentRelationshipTest(ClinicalTestCase):
    """The relationship the authorization rules depend on."""

    def _visit(self):
        from telemedicine.booking import BookingService
        from telemedicine.models import Role
        from telemedicine.records import RecordsService
        from telemedicine.auth import AuthService

        records = self.make_records()
        slots = self.make_slots()
        auth = AuthService(audit=records.audit, password_iterations=1000)
        patient_id = str(uuid.uuid4())
        practitioner_id = str(uuid.uuid4())
        patient_account = auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                        record_id=patient_id)
        practitioner_account = auth.register("dr@example.org", "a-long-passphrase",
                                             Role.PRACTITIONER,
                                             record_id=practitioner_id)
        patient = self.patient(user_id=patient_account.user_id, patient_id=patient_id)
        practitioner = self.practitioner(user_id=practitioner_account.user_id,
                                         practitioner_id=practitioner_id)
        self.store.save_patient(patient)
        self.store.save_practitioner(practitioner)
        booking = BookingService(slots, records=records, accounts=auth.users,
                                 audit=records.audit)
        slot = slots.create_slot(
            practitioner_account, practitioner_id=practitioner.practitioner_id,
            local_start=datetime(2026, 10, 21, 14, 0),
            local_end=datetime(2026, 10, 21, 14, 30), timezone_name="Europe/Berlin")
        appointment = booking.book(patient_account, slot.slot_id)
        return records, booking, patient, practitioner, patient_account, slot, appointment

    def test_the_treating_clinician_is_found_from_the_data(self):
        records, _booking, patient, practitioner, _account, _slot, _appointment = self._visit()
        # The records service works out who treats whom from the appointments
        # and the encounters, and it does it from the database.
        treated = records.patients_treated_by(practitioner.user_id)
        self.assertEqual(len(treated), 1)
        self.assertEqual(treated[0].mrn, "MRN-000123")

    def test_the_appointment_survives_and_keeps_its_accounts(self):
        records, _booking, patient, practitioner, _account, _slot, appointment = self._visit()
        reopened = self.make_records()
        found = reopened.get_appointment(appointment.appointment_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.patient_user_id, patient.user_id)
        self.assertEqual(found.practitioner_user_id, practitioner.user_id)
        self.assertEqual(found.status, "booked")

    def test_a_patient_can_still_read_their_own_appointment(self):
        records, _booking, _patient, _practitioner, account, _slot, appointment = self._visit()
        read = records.read_appointment(account, appointment.appointment_id)
        self.assertEqual(read.appointment_id, appointment.appointment_id)


class PrescriptionTest(ClinicalTestCase):
    """A prescription in the database, with the Nigerian dispensing identity."""

    def _visit(self):
        """A booked visit, an encounter, and the services that made them."""
        from telemedicine.auth import AuthService
        from telemedicine.booking import BookingService
        from telemedicine.models import Role
        from telemedicine.records import RecordsService

        records = self.make_records()
        slots = self.make_slots()
        auth = AuthService(audit=records.audit, password_iterations=1000)
        patient_id = str(uuid.uuid4())
        practitioner_id = str(uuid.uuid4())
        patient_account = auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                        record_id=patient_id)
        practitioner_account = auth.register("dr@example.org", "a-long-passphrase",
                                             Role.PRACTITIONER,
                                             record_id=practitioner_id)
        self.store.save_patient(self.patient(user_id=patient_account.user_id,
                                             patient_id=patient_id))
        self.store.save_practitioner(self.practitioner(
            user_id=practitioner_account.user_id, practitioner_id=practitioner_id))
        booking = BookingService(slots, records=records, accounts=auth.users,
                                 audit=records.audit)
        slot = slots.create_slot(
            practitioner_account,
            practitioner_id=practitioner_id,
            local_start=datetime(2026, 10, 21, 14, 0),
            local_end=datetime(2026, 10, 21, 14, 30), timezone_name="Europe/Berlin")
        appointment = booking.book(patient_account, slot.slot_id)
        encounter = records.create_encounter(
            practitioner_account, appointment.appointment_id,
            started_at=NOW, ended_at=NOW)
        return records, practitioner_account, encounter

    def _issue(self, records, practitioner_account, encounter, **overrides):
        arguments = {
            "medication_code": "AMOX-500-CAP",
            "medication_display": "Amoxicillin 500 mg capsule",
            "dosage_text": "Take one capsule by mouth three times a day for 5 days.",
            "brand_name": "Emoclox",
            "generic_name": "Amoxicillin 500mg",
            "strength": "500mg Capsules",
            "nafdac_number": "A4-1234",
        }
        arguments.update(overrides)
        return records.issue_prescription(practitioner_account, encounter.encounter_id,
                                          **arguments)

    def test_the_dispensing_identity_round_trips(self):
        records, practitioner_account, encounter = self._visit()
        prescription = self._issue(records, practitioner_account, encounter)
        found = self.store.get_prescription(prescription.prescription_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.brand_name, "Emoclox")
        self.assertEqual(found.generic_name, "Amoxicillin 500mg")
        self.assertEqual(found.strength, "500mg Capsules")
        self.assertEqual(found.nafdac_number, "A4-1234")
        self.assertEqual(found.medication_code, "AMOX-500-CAP")

    def test_the_database_refuses_a_nafdac_number_of_the_wrong_shape(self):
        records, practitioner_account, encounter = self._visit()
        prescription = self._issue(records, practitioner_account, encounter)
        # The service refuses one before the database is asked; this is the
        # database's own answer, for a row written past the service.
        import dataclasses
        broken = dataclasses.replace(prescription, nafdac_number="nonsense")
        with self.assertRaises(Exception) as caught:
            self.store.save_prescription(broken)
        self.assertIn("medication_request_nafdac_format", str(caught.exception))

    def test_the_database_refuses_a_prescription_without_a_brand(self):
        records, practitioner_account, encounter = self._visit()
        import dataclasses
        prescription = self._issue(records, practitioner_account, encounter)
        broken = dataclasses.replace(prescription, brand_name="")
        with self.assertRaises(Exception) as caught:
            self.store.save_prescription(broken)
        self.assertIn("brand_name", str(caught.exception))


class DoubleBookingTest(ClinicalTestCase):
    """Two instances, one slot, one appointment."""

    def _services(self, create_records=True):
        from telemedicine.auth import AuthService
        from telemedicine.booking import BookingService
        from telemedicine.models import Role

        records = self.make_records()
        slots = self.make_slots()
        auth = AuthService(audit=records.audit, password_iterations=1000)
        patient_id = str(uuid.uuid4())
        practitioner_id = str(uuid.uuid4())
        patient_account = auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                        record_id=patient_id)
        practitioner_account = auth.register("dr@example.org", "a-long-passphrase",
                                             Role.PRACTITIONER,
                                             record_id=practitioner_id)
        patient = self.patient(user_id=patient_account.user_id, patient_id=patient_id)
        practitioner = self.practitioner(user_id=practitioner_account.user_id,
                                         practitioner_id=practitioner_id)
        if create_records:
            self.store.save_patient(patient)
            self.store.save_practitioner(practitioner)
        booking = BookingService(slots, records=records, accounts=auth.users,
                                 audit=records.audit)
        return booking, slots, records, patient_account, practitioner_account, practitioner

    def test_a_slot_booked_by_one_instance_is_booked_for_the_other(self):
        from telemedicine.errors import ConflictError

        booking, slots, _records, patient_account, practitioner_account, practitioner = \
            self._services()
        slot = slots.create_slot(
            practitioner_account, practitioner_id=practitioner.practitioner_id,
            local_start=datetime(2026, 10, 21, 14, 0),
            local_end=datetime(2026, 10, 21, 14, 30), timezone_name="Europe/Berlin")
        booking.book(patient_account, slot.slot_id)

        # A second instance, with its own services, over the same database.
        other_booking, _other_slots, _other_records, _other_patient, _other_practitioner, _p = \
            self._services(create_records=False)
        with self.assertRaises(ConflictError):
            other_booking.book(patient_account, slot.slot_id)

    def test_two_instances_racing_for_one_slot_produce_one_appointment(self):
        # The service's check is a courtesy; the partial unique index of
        # ENG-003 is the guarantee, and it is what stops the race.
        from telemedicine.errors import ConflictError

        booking, slots, _records, patient_account, practitioner_account, practitioner = \
            self._services()
        slot = slots.create_slot(
            practitioner_account, practitioner_id=practitioner.practitioner_id,
            local_start=datetime(2026, 10, 21, 14, 0),
            local_end=datetime(2026, 10, 21, 14, 30), timezone_name="Europe/Berlin")

        outcomes = []

        def book(actor):
            try:
                booking.book(actor, slot.slot_id)
                outcomes.append("booked")
            except ConflictError:
                outcomes.append("refused")
            except Exception as error:  # pragma: no cover - a failure is the point
                outcomes.append(type(error).__name__)

        threads = [threading.Thread(target=book, args=(patient_account,)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(sorted(outcomes), ["booked", "refused"])
        records = self.make_records()
        appointments = [item for item in records.list_appointments()
                        if item.slot_id == slot.slot_id and item.status != "cancelled"]
        self.assertEqual(len(appointments), 1)

    def test_a_cancelled_appointment_frees_the_slot(self):
        booking, slots, records, patient_account, practitioner_account, practitioner = \
            self._services()
        slot = slots.create_slot(
            practitioner_account, practitioner_id=practitioner.practitioner_id,
            local_start=datetime(2026, 10, 21, 14, 0),
            local_end=datetime(2026, 10, 21, 14, 30), timezone_name="Europe/Berlin")
        appointment = booking.book(patient_account, slot.slot_id)
        booking.cancel(patient_account, appointment.appointment_id, reason="cannot make it")

        # The slot is free again, and it can be booked.
        again = booking.book(patient_account, slot.slot_id)
        self.assertNotEqual(again.appointment_id, appointment.appointment_id)
        active = [item for item in records.list_appointments()
                   if item.slot_id == slot.slot_id and item.status != "cancelled"]
        self.assertEqual(len(active), 1)


if __name__ == "__main__":
    unittest.main()
