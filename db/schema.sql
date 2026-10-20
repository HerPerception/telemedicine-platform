-- ENG-001 — telemedicine-platform core data model (PostgreSQL).
--
-- Scope: the six clinical entities defined by ENG-001:
--   patient, practitioner, schedule_slot, appointment, encounter, medication_request.
--
-- Out of scope (owned by other backlog items, deliberately absent here):
--   * Authentication, authorization, audit log        -> ENG-002
--   * Availability rules, reminders, notifications     -> ENG-003
--   * Video room lifecycle                            -> ENG-004
--   * Prescription document rendering / PDF storage   -> ENG-005
--   * FHIR REST layer, search parameters, profiles     -> ENG-006
--
-- Conventions (see docs/data-model.md):
--   * Primary keys are UUID v4 and are the source of the FHIR `id` element.
--   * All instants are `timestamptz` and are stored in UTC. The IANA time zone
--     that a practitioner sees the instant in is stored alongside it in a
--     `timezone` column using a `text` IANA name (e.g. 'America/New_York').
--   * Clinical rows are never cascade-deleted; foreign keys use ON DELETE RESTRICT.
--
-- Target: PostgreSQL 13+ (13 provides gen_random_uuid() in core).
-- For PostgreSQL 12 and older, also run: CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- btree_gist is required for the GiST exclusion constraint on schedule_slot.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- patient
-- ---------------------------------------------------------------------------
CREATE TABLE patient (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Business identifier surfaced as Patient.identifier (system .../identifier/mrn).
    mrn                 text        NOT NULL UNIQUE,
    family_name         text        NOT NULL,
    given_names         text[]      NOT NULL DEFAULT '{}',
    birth_date          date,
    -- administrative-gender value set; 'unknown' is used when the value is not
    -- disclosed (the R4 binding is "required", so a value must always be sent).
    gender              text        NOT NULL DEFAULT 'unknown'
                                    CHECK (gender IN ('male', 'female', 'other', 'unknown')),
    phone               text,
    email               text,
    address_line1       text,
    address_line2       text,
    address_city        text,
    address_region      text,
    address_postal_code text,
    address_country     text,
    -- Opaque pointer to the login account owned by ENG-002. Text, not a foreign
    -- key, so that ENG-001 does not pre-empt ENG-002's schema.
    account_ref         text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT patient_birth_date_not_future
        CHECK (birth_date IS NULL OR birth_date <= current_date)
);

-- ---------------------------------------------------------------------------
-- practitioner
-- ---------------------------------------------------------------------------
CREATE TABLE practitioner (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- National Provider Identifier -> Practitioner.identifier
    -- (system http://hl7.org/fhir/sid/us-npi). Optional: not every
    -- jurisdiction issues one and the MVP allows a locally identified clinician.
    npi             text        UNIQUE,
    family_name     text        NOT NULL,
    given_names     text[]      NOT NULL DEFAULT '{}',
    -- Post-nominal letters, e.g. {'MD', 'DO'}. Part of Practitioner.name.suffix.
    credentials     text[]      NOT NULL DEFAULT '{}',
    license_number  text,
    license_region  text,
    -- The R4 administrative-gender binding is "required"; 'unknown' is sent
    -- when the value is not recorded.
    gender          text        NOT NULL DEFAULT 'unknown'
                                CHECK (gender IN ('male', 'female', 'other', 'unknown')),
    specialty       text,
    -- IANA time zone the practitioner practises in. Slots are defined by a
    -- local wall-clock time in this zone and materialised as UTC instants.
    timezone        text        NOT NULL DEFAULT 'UTC',
    account_ref     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- schedule_slot — a bookable window in a practitioner's schedule.
-- ---------------------------------------------------------------------------
-- FHIR: the Slot resource. The MVP exposes five core resources, so Slot is
-- stored and mapped but is not a first-class FHIR endpoint in ENG-006; it is
-- referenced by Appointment.slot.
CREATE TABLE schedule_slot (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    practitioner_id uuid        NOT NULL REFERENCES practitioner (id) ON DELETE RESTRICT,
    starts_at       timestamptz NOT NULL,
    ends_at         timestamptz NOT NULL,
    -- IANA zone used to render the slot to the practitioner.
    timezone        text        NOT NULL,
    status          text        NOT NULL DEFAULT 'free'
                                CHECK (status IN ('free', 'busy', 'busy-tentative',
                                                  'busy-unavailable', 'entered-in-error')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT schedule_slot_ends_after_start CHECK (ends_at > starts_at),
    CONSTRAINT schedule_slot_minute_granularity
        CHECK (starts_at = date_trunc('minute', starts_at)
               AND ends_at = date_trunc('minute', ends_at)),
    CONSTRAINT schedule_slot_duration_positive
        CHECK ((ends_at - starts_at) BETWEEN INTERVAL '1 minute' AND INTERVAL '12 hours'),
    -- Unique target for the appointment composite foreign key below.
    CONSTRAINT schedule_slot_identity
        UNIQUE (id, practitioner_id, starts_at, ends_at)
);

-- No practitioner may have two overlapping slots. This is the first line of
-- defence against double-booking; the second is appointment.slot_id UNIQUE.
CREATE INDEX schedule_slot_practitioner_range
    ON schedule_slot USING gist (practitioner_id, tstzrange(starts_at, ends_at));

ALTER TABLE schedule_slot
    ADD CONSTRAINT schedule_slot_no_overlap
    EXCLUDE USING gist (practitioner_id WITH =,
                        tstzrange(starts_at, ends_at) WITH &&);

-- ---------------------------------------------------------------------------
-- appointment
-- ---------------------------------------------------------------------------
CREATE TABLE appointment (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          uuid        NOT NULL REFERENCES patient (id) ON DELETE RESTRICT,
    practitioner_id     uuid        NOT NULL REFERENCES practitioner (id) ON DELETE RESTRICT,
    -- Amended by ENG-003: the uniqueness of the slot is enforced by the
    -- partial unique index below, so that a cancelled appointment keeps its
    -- reference to the slot it occupied while the slot becomes bookable
    -- again.
    slot_id             uuid        NOT NULL,
    status              text        NOT NULL
                                    CHECK (status IN ('proposed', 'pending', 'booked', 'arrived',
                                                      'fulfilled', 'cancelled', 'noshow',
                                                      'entered-in-error', 'checked-in', 'waitlist')),
    starts_at           timestamptz NOT NULL,
    ends_at             timestamptz NOT NULL,
    duration_minutes    integer     NOT NULL CHECK (duration_minutes > 0),
    -- Reason for visit. See the encounter-reason value set in the mapping doc.
    reason_code         text,
    reason_text         text,
    -- Free text shown to the patient before the visit.
    patient_note        text,
    cancellation_reason text,
    cancelled_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    -- The booked slot, the practitioner and the appointment window must all
    -- agree. A composite foreign key enforces this in the database.
    CONSTRAINT appointment_slot_match
        FOREIGN KEY (slot_id, practitioner_id, starts_at, ends_at)
        REFERENCES schedule_slot (id, practitioner_id, starts_at, ends_at)
        ON DELETE RESTRICT,
    CONSTRAINT appointment_ends_after_start CHECK (ends_at > starts_at),
    CONSTRAINT appointment_duration_matches_window
        CHECK (duration_minutes = (extract(epoch FROM (ends_at - starts_at)) / 60)::integer),
    CONSTRAINT appointment_cancelled_has_reason
        CHECK (status <> 'cancelled' OR (cancellation_reason IS NOT NULL
                                         AND cancelled_at IS NOT NULL)),
    -- Unique target for the encounter composite foreign key below.
    CONSTRAINT appointment_identity
        UNIQUE (id, patient_id, practitioner_id)
);

CREATE INDEX appointment_practitioner_start ON appointment (practitioner_id, starts_at);
CREATE INDEX appointment_patient_start      ON appointment (patient_id, starts_at);
CREATE INDEX appointment_status             ON appointment (status);

-- At most one *active* appointment may occupy a slot. A cancelled
-- appointment keeps its reference to the slot it occupied, so the record of
-- what was booked and released is not lost, and the slot can be booked
-- again. Without this, cancelling an appointment would leave the slot
-- unusable for ever, because the old unique constraint would still see the
-- cancelled appointment's row.
CREATE UNIQUE INDEX appointment_active_slot_key
    ON appointment (slot_id) WHERE status <> 'cancelled';

-- ---------------------------------------------------------------------------
-- encounter — the clinical encounter produced by a visit.
-- ---------------------------------------------------------------------------
CREATE TABLE encounter (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id     uuid        NOT NULL UNIQUE,
    patient_id         uuid        NOT NULL REFERENCES patient (id) ON DELETE RESTRICT,
    practitioner_id    uuid        NOT NULL REFERENCES practitioner (id) ON DELETE RESTRICT,
    status             text        NOT NULL
                                   CHECK (status IN ('planned', 'arrived', 'triaged', 'in-progress',
                                                     'onleave', 'finished', 'cancelled',
                                                     'entered-in-error', 'unknown')),
    -- v3 ActEncounterCode. 'AMB' = ambulatory.
    encounter_class    text        NOT NULL DEFAULT 'AMB',
    -- v3 ActCode. 'VR' = virtual. The MVP supports one consultation modality
    -- (browser video), and v3-ActCode has no telephone code, so the value set
    -- is deliberately narrow.
    encounter_type     text        NOT NULL DEFAULT 'VR'
                                    CHECK (encounter_type IN ('VR')),
    started_at         timestamptz NOT NULL,
    ended_at           timestamptz,
    reason_code        text,
    -- Patient's presenting complaint -> Encounter.reasonCode.text.
    chief_complaint    text,
    -- Free-text clinical note. R4 Encounter has no free-text note element, so
    -- it is carried in a declared extension (see docs/fhir-mappings.md).
    clinical_note      text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    -- The encounter must belong to the same patient and practitioner as the
    -- appointment it came from.
    CONSTRAINT encounter_appointment_match
        FOREIGN KEY (appointment_id, patient_id, practitioner_id)
        REFERENCES appointment (id, patient_id, practitioner_id)
        ON DELETE RESTRICT,
    CONSTRAINT encounter_ends_after_start
        CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE INDEX encounter_patient_started ON encounter (patient_id, started_at);
CREATE INDEX encounter_practitioner    ON encounter (practitioner_id);

-- ---------------------------------------------------------------------------
-- medication_request — the e-prescription.
-- ---------------------------------------------------------------------------
CREATE TABLE medication_request (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id        uuid        NOT NULL REFERENCES encounter (id) ON DELETE RESTRICT,
    patient_id          uuid        NOT NULL REFERENCES patient (id) ON DELETE RESTRICT,
    prescriber_id       uuid        NOT NULL REFERENCES practitioner (id) ON DELETE RESTRICT,
    status              text        NOT NULL
                                    CHECK (status IN ('active', 'on-hold', 'completed', 'cancelled',
                                                      'entered-in-error', 'draft', 'stopped',
                                                      'unknown')),
    intent              text        NOT NULL DEFAULT 'order'
                                    CHECK (intent IN ('proposal', 'plan', 'order', 'original-order',
                                                      'reflex-order', 'filler-order',
                                                      'instance-order', 'option')),
    -- Local medication catalogue. The MVP has no pharmacy/eRx integration, so
    -- a local code system is authoritative until OPS-001 settles the
    -- terminology source. See docs/fhir-mappings.md.
    medication_system   text        NOT NULL,
    medication_code     text        NOT NULL,
    medication_display  text        NOT NULL,
    authored_on         timestamptz NOT NULL,
    -- Human-readable directions -> MedicationRequest.dosageInstruction.text.
    dosage_text         text        NOT NULL,
    dose_quantity       numeric(10, 3),
    dose_unit           text,
    route_text          text,
    duration_days       integer     CHECK (duration_days IS NULL OR duration_days > 0),
    -- DispenseRequest.numberOfRepeatsAllowed
    refills             integer     CHECK (refills IS NULL OR refills >= 0),
    -- DispenseRequest.quantity.value
    dispense_quantity   numeric(10, 3),
    notes               text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    -- The prescription must belong to the same patient and prescriber as the
    -- encounter it was issued during.
    CONSTRAINT medication_request_encounter_match
        FOREIGN KEY (encounter_id, patient_id, prescriber_id)
        REFERENCES encounter (id, patient_id, practitioner_id)
        ON DELETE RESTRICT
);

CREATE INDEX medication_request_patient_authored
    ON medication_request (patient_id, authored_on);
CREATE INDEX medication_request_encounter ON medication_request (encounter_id);
CREATE INDEX medication_request_prescriber ON medication_request (prescriber_id);

-- ---------------------------------------------------------------------------
-- Comments on maintenance behaviour.
-- ---------------------------------------------------------------------------
-- updated_at is set by the application layer on every write. It is not a
-- database trigger in ENG-001: ENG-002 introduces the shared write path
-- (authentication, authorization, audit) and that is the right place to add
-- one consistent trigger for every table.
