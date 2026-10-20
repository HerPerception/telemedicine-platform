"""Where the records of the application live.

The services of ENG-002 and ENG-003 kept their records in dictionaries. That
was the right thing while there was no database, and it is the wrong thing
now: a record that lives in the memory of one process is neither shared
between the instances of the application nor durable.

This module defines where the records go, and the implementation that keeps
them in memory. The database implementation is in
``telemedicine.persistence.clinical_store``.

Nothing here imports the domain types on purpose. The records are passed
through as they are, so this module stays free of a cycle with the services
that use it.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional


class ClinicalRepository:
    """The clinical records: patients, practitioners, appointments, encounters
    and prescriptions.

    A record is saved by its id: saving a record that is already there
    replaces it, which is what the services do when they change one.
    """

    # -- patients ----------------------------------------------------------

    def save_patient(self, patient):
        raise NotImplementedError

    def get_patient(self, patient_id: str):
        raise NotImplementedError

    def list_patients(self) -> List:
        raise NotImplementedError

    # -- practitioners -----------------------------------------------------

    def save_practitioner(self, practitioner):
        raise NotImplementedError

    def get_practitioner(self, practitioner_id: str):
        raise NotImplementedError

    def list_practitioners(self) -> List:
        raise NotImplementedError

    # -- appointments ------------------------------------------------------

    def save_appointment(self, appointment):
        raise NotImplementedError

    def get_appointment(self, appointment_id: str):
        raise NotImplementedError

    def list_appointments(self) -> List:
        raise NotImplementedError

    def appointment_for_slot(self, slot_id: str):
        """The appointment that occupies a slot, or None.

        A slot holds at most one *active* appointment: a cancelled one does
        not hold it, which is what lets the slot be booked again.
        """
        raise NotImplementedError

    # -- encounters --------------------------------------------------------

    def save_encounter(self, encounter):
        raise NotImplementedError

    def get_encounter(self, encounter_id: str):
        raise NotImplementedError

    def list_encounters(self) -> List:
        raise NotImplementedError

    def encounter_for_appointment(self, appointment_id: str):
        """The encounter of an appointment, or None."""
        raise NotImplementedError

    # -- prescriptions -----------------------------------------------------

    def save_prescription(self, prescription):
        raise NotImplementedError

    def get_prescription(self, prescription_id: str):
        raise NotImplementedError

    def list_prescriptions(self) -> List:
        raise NotImplementedError

    def prescriptions_for_encounter(self, encounter_id: str) -> List:
        raise NotImplementedError


class SlotRepository:
    """The bookable windows of the practitioners' schedules."""

    def save_slot(self, slot):
        raise NotImplementedError

    def get_slot(self, slot_id: str):
        raise NotImplementedError

    def list_slots(self) -> List:
        raise NotImplementedError

    def slots_for_practitioner(self, practitioner_id: str) -> List:
        raise NotImplementedError


class InMemoryClinicalRepository(ClinicalRepository):
    """The clinical records, in the memory of one process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._patients: Dict[str, object] = {}
        self._practitioners: Dict[str, object] = {}
        self._appointments: Dict[str, object] = {}
        self._encounters: Dict[str, object] = {}
        self._prescriptions: Dict[str, object] = {}

    def save_patient(self, patient):
        with self._lock:
            self._patients[patient.patient_id] = patient
        return patient

    def get_patient(self, patient_id: str):
        with self._lock:
            return self._patients.get(patient_id)

    def list_patients(self) -> List:
        with self._lock:
            return list(self._patients.values())

    def save_practitioner(self, practitioner):
        with self._lock:
            self._practitioners[practitioner.practitioner_id] = practitioner
        return practitioner

    def get_practitioner(self, practitioner_id: str):
        with self._lock:
            return self._practitioners.get(practitioner_id)

    def list_practitioners(self) -> List:
        with self._lock:
            return list(self._practitioners.values())

    def save_appointment(self, appointment):
        with self._lock:
            self._appointments[appointment.appointment_id] = appointment
        return appointment

    def get_appointment(self, appointment_id: str):
        with self._lock:
            return self._appointments.get(appointment_id)

    def list_appointments(self) -> List:
        with self._lock:
            return list(self._appointments.values())

    def appointment_for_slot(self, slot_id: str):
        with self._lock:
            for appointment in self._appointments.values():
                if appointment.slot_id == slot_id and appointment.status != "cancelled":
                    return appointment
        return None

    def save_encounter(self, encounter):
        with self._lock:
            self._encounters[encounter.encounter_id] = encounter
        return encounter

    def get_encounter(self, encounter_id: str):
        with self._lock:
            return self._encounters.get(encounter_id)

    def list_encounters(self) -> List:
        with self._lock:
            return list(self._encounters.values())

    def encounter_for_appointment(self, appointment_id: str):
        with self._lock:
            for encounter in self._encounters.values():
                if encounter.appointment_id == appointment_id:
                    return encounter
        return None

    def save_prescription(self, prescription):
        with self._lock:
            self._prescriptions[prescription.prescription_id] = prescription
        return prescription

    def get_prescription(self, prescription_id: str):
        with self._lock:
            return self._prescriptions.get(prescription_id)

    def list_prescriptions(self) -> List:
        with self._lock:
            return list(self._prescriptions.values())

    def prescriptions_for_encounter(self, encounter_id: str) -> List:
        with self._lock:
            return [prescription for prescription in self._prescriptions.values()
                    if prescription.encounter_id == encounter_id]


class InMemorySlotRepository(SlotRepository):
    """The slots, in the memory of one process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._slots: Dict[str, object] = {}

    def save_slot(self, slot):
        with self._lock:
            self._slots[slot.slot_id] = slot
        return slot

    def get_slot(self, slot_id: str):
        with self._lock:
            return self._slots.get(slot_id)

    def list_slots(self) -> List:
        with self._lock:
            return list(self._slots.values())

    def slots_for_practitioner(self, practitioner_id: str) -> List:
        with self._lock:
            return [slot for slot in self._slots.values()
                    if slot.practitioner_id == practitioner_id]
