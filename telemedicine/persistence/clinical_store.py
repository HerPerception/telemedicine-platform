"""The clinical records, in the database.

This is the implementation of :class:`telemedicine.repositories.ClinicalRepository`
and :class:`telemedicine.repositories.SlotRepository` that puts the records of
ENG-001 in the tables of ``db/schema.sql``.

Two details are worth knowing.

**The account link lives on the clinical rows.** ``patient.account_ref`` and
``practitioner.account_ref`` hold the id of the account the row belongs to —
the link that ENG-001's schema declares and that ENG-002's records carry. The
appointment, the encounter, the prescription and the slot store the *clinical*
id, and the account id is resolved with a join. That way there is one place
where "which account is this patient" is written, and it cannot disagree with
itself.

**The display name is derived.** The tables hold the name parts — the family
name and the given names — and the display name is assembled from them,
because the display name is a presentation of the parts rather than a fact of
its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from telemedicine.errors import ConflictError
from telemedicine.persistence.database import Database
from telemedicine.records import (
    Appointment,
    Encounter,
    PatientRecord,
    PractitionerRecord,
    Prescription,
)


def _is_unique_violation(error) -> bool:
    """Whether an error is the database refusing a duplicate.

    The check is on the SQLSTATE rather than on the driver's exception type,
    so it does not depend on which version of the driver is installed.
    """
    sqlstate = getattr(getattr(error, "diag", None), "sqlstate", None)
    return sqlstate == "23505"


def _as_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _display_name(family_name: Optional[str], given_names, credentials=()) -> str:
    parts = list(given_names or [])
    if family_name:
        parts.append(family_name)
    parts.extend(credentials or [])
    return " ".join(parts)


class PostgresClinicalRepository:
    """The clinical records, in the tables of ``db/schema.sql``."""

    def __init__(self, database: Database):
        self.database = database

    # -- patients ----------------------------------------------------------

    def save_patient(self, patient: PatientRecord) -> PatientRecord:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO patient (id, mrn, family_name, given_names, birth_date, gender,"
                " phone, email, address_line1, address_line2, address_city, address_region,"
                " address_postal_code, address_country, account_ref, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())"
                " ON CONFLICT (id) DO UPDATE SET"
                " mrn = EXCLUDED.mrn, family_name = EXCLUDED.family_name,"
                " given_names = EXCLUDED.given_names, birth_date = EXCLUDED.birth_date,"
                " gender = EXCLUDED.gender, phone = EXCLUDED.phone, email = EXCLUDED.email,"
                " address_line1 = EXCLUDED.address_line1,"
                " address_line2 = EXCLUDED.address_line2,"
                " address_city = EXCLUDED.address_city,"
                " address_region = EXCLUDED.address_region,"
                " address_postal_code = EXCLUDED.address_postal_code,"
                " address_country = EXCLUDED.address_country,"
                " account_ref = EXCLUDED.account_ref, updated_at = EXCLUDED.updated_at",
                (patient.patient_id, patient.mrn, patient.family_name,
                 list(patient.given_names), patient.date_of_birth, patient.gender,
                 patient.phone, patient.email,
                 patient.address_line[0] if len(patient.address_line) > 0 else None,
                 patient.address_line[1] if len(patient.address_line) > 1 else None,
                 patient.address_city, patient.address_region, patient.address_postal_code,
                 patient.address_country, patient.user_id))
        return patient

    def get_patient(self, patient_id: str) -> Optional[PatientRecord]:
        rows = self._query(
            "SELECT id, mrn, family_name, given_names, birth_date, gender, phone, email,"
            " address_line1, address_line2, address_city, address_region,"
            " address_postal_code, address_country, account_ref, created_at"
            " FROM patient WHERE id = %s", (patient_id,))
        return _to_patient(rows[0]) if rows else None

    def list_patients(self) -> List[PatientRecord]:
        rows = self._query(
            "SELECT id, mrn, family_name, given_names, birth_date, gender, phone, email,"
            " address_line1, address_line2, address_city, address_region,"
            " address_postal_code, address_country, account_ref, created_at"
            " FROM patient ORDER BY id")
        return [_to_patient(row) for row in rows]

    # -- practitioners -----------------------------------------------------

    def save_practitioner(self, practitioner: PractitionerRecord) -> PractitionerRecord:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO practitioner (id, npi, family_name, given_names, credentials,"
                " license_number, license_region, gender, specialty, timezone, account_ref,"
                " created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " npi = EXCLUDED.npi, family_name = EXCLUDED.family_name,"
                " given_names = EXCLUDED.given_names, credentials = EXCLUDED.credentials,"
                " license_number = EXCLUDED.license_number,"
                " license_region = EXCLUDED.license_region, gender = EXCLUDED.gender,"
                " specialty = EXCLUDED.specialty, account_ref = EXCLUDED.account_ref,"
                " updated_at = EXCLUDED.updated_at",
                (practitioner.practitioner_id, practitioner.identifier,
                 practitioner.family_name, list(practitioner.given_names),
                 list(practitioner.credentials), practitioner.license_number,
                 practitioner.license_region, practitioner.gender, practitioner.specialty,
                 "UTC", practitioner.user_id, datetime.now(timezone.utc),
                 datetime.now(timezone.utc)))
        return practitioner

    def get_practitioner(self, practitioner_id: str) -> Optional[PractitionerRecord]:
        rows = self._query(
            "SELECT id, npi, family_name, given_names, credentials, license_number,"
            " license_region, gender, specialty, account_ref, created_at"
            " FROM practitioner WHERE id = %s", (practitioner_id,))
        return _to_practitioner(rows[0]) if rows else None

    def list_practitioners(self) -> List[PractitionerRecord]:
        rows = self._query(
            "SELECT id, npi, family_name, given_names, credentials, license_number,"
            " license_region, gender, specialty, account_ref, created_at"
            " FROM practitioner ORDER BY id")
        return [_to_practitioner(row) for row in rows]

    # -- appointments ------------------------------------------------------

    def save_appointment(self, appointment: Appointment) -> Appointment:
        try:
            with self.database.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO appointment (id, patient_id, practitioner_id, slot_id, status,"
                    " starts_at, ends_at, duration_minutes, reason_code, reason_text,"
                    " patient_note, cancellation_reason, cancelled_at, created_at, updated_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (id) DO UPDATE SET"
                    " patient_id = EXCLUDED.patient_id,"
                    " practitioner_id = EXCLUDED.practitioner_id,"
                    " slot_id = EXCLUDED.slot_id, status = EXCLUDED.status,"
                    " starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,"
                    " duration_minutes = EXCLUDED.duration_minutes,"
                    " reason_code = EXCLUDED.reason_code, reason_text = EXCLUDED.reason_text,"
                    " patient_note = EXCLUDED.patient_note,"
                    " cancellation_reason = EXCLUDED.cancellation_reason,"
                    " cancelled_at = EXCLUDED.cancelled_at, updated_at = EXCLUDED.updated_at",
                    (appointment.appointment_id, appointment.patient_id,
                     appointment.practitioner_id, appointment.slot_id, appointment.status,
                     appointment.starts_at, appointment.ends_at,
                     int((appointment.ends_at - appointment.starts_at).total_seconds() // 60),
                     appointment.reason_code, appointment.reason_text, appointment.patient_note,
                     appointment.cancellation_reason, appointment.cancelled_at,
                     appointment.created_at or datetime.now(timezone.utc),
                     datetime.now(timezone.utc)))
        except Exception as error:
            # The partial unique index over the active appointments of a slot
            # is the real guard against double-booking, and it fires when two
            # instances book the same slot at the same moment. The check in
            # the service is a courtesy; this is the guarantee.
            if _is_unique_violation(error):
                raise ConflictError("the slot is no longer available") from error
            raise
        return appointment

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        rows = self._query(_APPOINTMENT_SELECT + " WHERE a.id = %s", (appointment_id,))
        return _to_appointment(rows[0]) if rows else None

    def list_appointments(self) -> List[Appointment]:
        rows = self._query(_APPOINTMENT_SELECT + " ORDER BY a.id")
        return [_to_appointment(row) for row in rows]

    def appointment_for_slot(self, slot_id: str) -> Optional[Appointment]:
        rows = self._query(
            _APPOINTMENT_SELECT + " WHERE a.slot_id = %s AND a.status <> 'cancelled' LIMIT 1",
            (slot_id,))
        return _to_appointment(rows[0]) if rows else None

    # -- encounters --------------------------------------------------------

    def save_encounter(self, encounter: Encounter) -> Encounter:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO encounter (id, appointment_id, patient_id, practitioner_id, status,"
                " encounter_class, encounter_type, started_at, ended_at, reason_code,"
                " chief_complaint, clinical_note, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " appointment_id = EXCLUDED.appointment_id,"
                " patient_id = EXCLUDED.patient_id,"
                " practitioner_id = EXCLUDED.practitioner_id, status = EXCLUDED.status,"
                " started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at,"
                " reason_code = EXCLUDED.reason_code,"
                " chief_complaint = EXCLUDED.chief_complaint,"
                " clinical_note = EXCLUDED.clinical_note, updated_at = EXCLUDED.updated_at",
                (encounter.encounter_id, encounter.appointment_id, encounter.patient_id,
                 encounter.practitioner_id, encounter.status, "AMB", "VR",
                 encounter.started_at, encounter.ended_at, None, encounter.chief_complaint,
                 encounter.clinical_note, datetime.now(timezone.utc),
                 datetime.now(timezone.utc)))
        return encounter

    def get_encounter(self, encounter_id: str) -> Optional[Encounter]:
        rows = self._query(_ENCOUNTER_SELECT + " WHERE e.id = %s", (encounter_id,))
        return _to_encounter(rows[0]) if rows else None

    def list_encounters(self) -> List[Encounter]:
        rows = self._query(_ENCOUNTER_SELECT + " ORDER BY e.id")
        return [_to_encounter(row) for row in rows]

    def encounter_for_appointment(self, appointment_id: str) -> Optional[Encounter]:
        rows = self._query(
            _ENCOUNTER_SELECT + " WHERE e.appointment_id = %s LIMIT 1", (appointment_id,))
        return _to_encounter(rows[0]) if rows else None

    # -- prescriptions -----------------------------------------------------

    def save_prescription(self, prescription: Prescription) -> Prescription:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO medication_request (id, encounter_id, patient_id, prescriber_id,"
                " medication_system, medication_code, medication_display, dosage_text, status,"
                " intent, authored_on, notes, refills, dispense_quantity, route_text,"
                " dose_quantity, dose_unit, duration_days, brand_name, generic_name, strength,"
                " nafdac_number, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                " %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " encounter_id = EXCLUDED.encounter_id, patient_id = EXCLUDED.patient_id,"
                " prescriber_id = EXCLUDED.prescriber_id,"
                " medication_system = EXCLUDED.medication_system,"
                " medication_code = EXCLUDED.medication_code,"
                " medication_display = EXCLUDED.medication_display,"
                " dosage_text = EXCLUDED.dosage_text, status = EXCLUDED.status,"
                " brand_name = EXCLUDED.brand_name, generic_name = EXCLUDED.generic_name,"
                " strength = EXCLUDED.strength, nafdac_number = EXCLUDED.nafdac_number,"
                " intent = EXCLUDED.intent, notes = EXCLUDED.notes, refills = EXCLUDED.refills,"
                " dispense_quantity = EXCLUDED.dispense_quantity,"
                " route_text = EXCLUDED.route_text, dose_quantity = EXCLUDED.dose_quantity,"
                " dose_unit = EXCLUDED.dose_unit, duration_days = EXCLUDED.duration_days,"
                " updated_at = EXCLUDED.updated_at",
                (prescription.prescription_id, prescription.encounter_id,
                 prescription.patient_id, prescription.prescriber_id,
                 prescription.medication_system, prescription.medication_code,
                 prescription.medication_display, prescription.dosage_text, prescription.status,
                 "order", prescription.authored_on, prescription.notes, prescription.refills,
                 prescription.dispense_quantity, prescription.route_text,
                 prescription.dose_quantity, prescription.dose_unit, prescription.duration_days,
                 prescription.brand_name, prescription.generic_name, prescription.strength,
                 prescription.nafdac_number,
                 datetime.now(timezone.utc), datetime.now(timezone.utc)))
        return prescription

    def get_prescription(self, prescription_id: str) -> Optional[Prescription]:
        rows = self._query(_PRESCRIPTION_SELECT + " WHERE m.id = %s", (prescription_id,))
        return _to_prescription(rows[0]) if rows else None

    def list_prescriptions(self) -> List[Prescription]:
        rows = self._query(_PRESCRIPTION_SELECT + " ORDER BY m.id")
        return [_to_prescription(row) for row in rows]

    def prescriptions_for_encounter(self, encounter_id: str) -> List[Prescription]:
        rows = self._query(
            _PRESCRIPTION_SELECT + " WHERE m.encounter_id = %s ORDER BY m.id", (encounter_id,))
        return [_to_prescription(row) for row in rows]

    # -- slots -------------------------------------------------------------

    def save_slot(self, slot) -> object:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO schedule_slot (id, practitioner_id, starts_at, ends_at, timezone,"
                " status, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " practitioner_id = EXCLUDED.practitioner_id,"
                " starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,"
                " timezone = EXCLUDED.timezone, status = EXCLUDED.status,"
                " updated_at = EXCLUDED.updated_at",
                (slot.slot_id, slot.practitioner_id, slot.starts_at, slot.ends_at,
                 slot.timezone, slot.status, datetime.now(timezone.utc),
                 datetime.now(timezone.utc)))
        return slot

    def get_slot(self, slot_id: str):
        rows = self._query(_SLOT_SELECT + " WHERE s.id = %s", (slot_id,))
        return _to_slot(rows[0]) if rows else None

    def list_slots(self) -> List:
        rows = self._query(_SLOT_SELECT + " ORDER BY s.id")
        return [_to_slot(row) for row in rows]

    def slots_for_practitioner(self, practitioner_id: str) -> List:
        rows = self._query(_SLOT_SELECT + " WHERE s.practitioner_id = %s ORDER BY s.id",
                           (practitioner_id,))
        return [_to_slot(row) for row in rows]

    # -- plumbing ----------------------------------------------------------

    def _query(self, statement: str, parameters: Tuple = ()) -> List[Tuple]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                return list(cursor.fetchall())


# The account id of the patient and of the practitioner, resolved through the
# account link the clinical rows carry.
_APPOINTMENT_SELECT = (
    "SELECT a.id, a.patient_id, a.practitioner_id, a.slot_id, a.status, a.starts_at, a.ends_at,"
    " a.reason_code, a.reason_text, a.patient_note, a.cancellation_reason, a.cancelled_at,"
    " a.created_at,"
    " p.account_ref, pr.account_ref"
    " FROM appointment a"
    " JOIN patient p ON p.id = a.patient_id"
    " JOIN practitioner pr ON pr.id = a.practitioner_id")

_ENCOUNTER_SELECT = (
    "SELECT e.id, e.appointment_id, e.patient_id, e.practitioner_id, e.status, e.started_at,"
    " e.ended_at, e.chief_complaint, e.clinical_note,"
    " p.account_ref, pr.account_ref"
    " FROM encounter e"
    " JOIN patient p ON p.id = e.patient_id"
    " JOIN practitioner pr ON pr.id = e.practitioner_id")

_PRESCRIPTION_SELECT = (
    "SELECT m.id, m.encounter_id, m.patient_id, m.prescriber_id, m.medication_system,"
    " m.medication_code, m.medication_display, m.dosage_text, m.status, m.authored_on,"
    " m.notes, m.refills, m.dispense_quantity, m.route_text, m.dose_quantity, m.dose_unit,"
    " m.duration_days, m.brand_name, m.generic_name, m.strength, m.nafdac_number,"
    " p.account_ref, pr.account_ref"
    " FROM medication_request m"
    " JOIN patient p ON p.id = m.patient_id"
    " JOIN practitioner pr ON pr.id = m.prescriber_id")

_SLOT_SELECT = (
    "SELECT s.id, s.practitioner_id, s.starts_at, s.ends_at, s.timezone, s.status,"
    " pr.account_ref"
    " FROM schedule_slot s"
    " JOIN practitioner pr ON pr.id = s.practitioner_id")


def _to_patient(row) -> PatientRecord:
    address_line = tuple(line for line in (row[8], row[9]) if line)
    return PatientRecord(
        patient_id=str(row[0]),
        user_id=row[14],
        display_name=_display_name(row[2], row[3]),
        date_of_birth=row[4],
        mrn=row[1],
        family_name=row[2],
        given_names=tuple(row[3] or ()),
        gender=row[5] or "unknown",
        phone=row[6],
        email=row[7],
        address_line=address_line,
        address_city=row[10],
        address_region=row[11],
        address_postal_code=row[12],
        address_country=row[13],
    )


def _to_practitioner(row) -> PractitionerRecord:
    return PractitionerRecord(
        practitioner_id=str(row[0]),
        user_id=row[9],
        display_name=_display_name(row[2], row[3], row[4]),
        identifier=row[1],
        specialty=row[8],
        family_name=row[2],
        given_names=tuple(row[3] or ()),
        credentials=tuple(row[4] or ()),
        gender=row[7] or "unknown",
        license_number=row[5],
        license_region=row[6],
    )


def _to_appointment(row) -> Appointment:
    return Appointment(
        appointment_id=str(row[0]),
        patient_id=str(row[1]),
        practitioner_id=str(row[2]),
        patient_user_id=row[13],
        practitioner_user_id=row[14],
        starts_at=_as_datetime(row[5]),
        ends_at=_as_datetime(row[6]),
        status=row[4],
        slot_id=str(row[3]) if row[3] is not None else None,
        reason_code=row[7],
        reason_text=row[8],
        patient_note=row[9],
        cancellation_reason=row[10],
        cancelled_at=_as_datetime(row[11]),
        created_at=_as_datetime(row[12]),
    )


def _to_encounter(row) -> Encounter:
    return Encounter(
        encounter_id=str(row[0]),
        appointment_id=str(row[1]),
        patient_id=str(row[2]),
        practitioner_id=str(row[3]),
        patient_user_id=row[9],
        practitioner_user_id=row[10],
        status=row[4],
        started_at=_as_datetime(row[5]),
        ended_at=_as_datetime(row[6]),
        chief_complaint=row[7],
        clinical_note=row[8],
    )


def _to_prescription(row) -> Prescription:
    return Prescription(
        prescription_id=str(row[0]),
        encounter_id=str(row[1]),
        patient_id=str(row[2]),
        prescriber_id=str(row[3]),
        patient_user_id=row[21],
        prescriber_user_id=row[22],
        medication_system=row[4],
        medication_code=row[5],
        medication_display=row[6],
        dosage_text=row[7],
        status=row[8],
        authored_on=_as_datetime(row[9]),
        notes=row[10],
        refills=row[11],
        dispense_quantity=row[12],
        route_text=row[13],
        dose_quantity=row[14],
        dose_unit=row[15],
        duration_days=row[16],
        brand_name=row[17] or "",
        generic_name=row[18] or "",
        strength=row[19],
        nafdac_number=row[20] or "",
    )


def _to_slot(row):
    from telemedicine.booking import Slot
    return Slot(
        slot_id=str(row[0]),
        practitioner_id=str(row[1]),
        practitioner_user_id=row[6],
        starts_at=_as_datetime(row[2]),
        ends_at=_as_datetime(row[3]),
        timezone=row[4],
        status=row[5],
    )
