-- ENG-003 (OPS-003) — the consent record.
--
-- Scope: the table behind `telemedicine.consent`. It records what a patient
-- has agreed to, and what they have withdrawn.
--
-- The shape of it follows the Nigeria Data Protection Act 2023:
--
-- * the clinical record does not rest on consent. Section 30(1)(g) allows
--   processing of sensitive personal data — health status is sensitive
--   personal data — where it is carried out for purposes of medical care or
--   community welfare by or under the responsibility of a professional
--   owing a duty of confidentiality. So the consultation record is made
--   under that ground, and the patient is told about it (the Section 27
--   notice) rather than asked to sign for it;
-- * the optional uses — research, teaching, marketing, sharing with a
--   partner — each need a consent of their own, given for the specific
--   purpose (Section 30(1)(a)), and each can be withdrawn on its own
--   (Section 35).
--
-- The table is append-only, like the audit log. A withdrawal is a new row,
-- not a change to the old one, so that what the patient agreed to and when
-- they stopped agreeing to it can both be shown.

CREATE TABLE IF NOT EXISTS consent_event (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The account the event is about.
    user_id             uuid        NOT NULL,
    -- granted, withdrawn, or acknowledged (the patient was shown the
    -- notice, which is not a consent).
    kind                text        NOT NULL
                                    CHECK (kind IN ('granted', 'withdrawn', 'acknowledged')),
    -- The optional purpose. Null for an acknowledgement of the notice.
    purpose             text,
    -- The version of the notice the patient saw. A consent is tied to it.
    notice_version      text        NOT NULL DEFAULT '',
    -- How the patient gave it.
    method              text        NOT NULL DEFAULT 'web',
    -- Whatever proves it: the address it was sent to, a reference, a
    -- witness. Free text, because it differs by practice.
    evidence            text,
    occurred_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT consent_event_purpose_known
        CHECK (purpose IS NULL
               OR purpose IN ('research', 'teaching', 'marketing', 'partner_sharing'))
);

-- Everything that happened for one account, in order.
CREATE INDEX IF NOT EXISTS consent_event_user ON consent_event (user_id, occurred_at);

-- Everything that happened for one account and one purpose, in order.
CREATE INDEX IF NOT EXISTS consent_event_purpose
    ON consent_event (user_id, purpose, occurred_at);

-- The record is append-only: a consent is evidence, and evidence is not
-- edited. Withdrawing writes a new row.
CREATE OR REPLACE FUNCTION consent_event_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'consent_event rows are append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS consent_event_no_update ON consent_event;
CREATE TRIGGER consent_event_no_update
    BEFORE UPDATE OR DELETE ON consent_event
    FOR EACH ROW EXECUTE FUNCTION consent_event_is_append_only();

DROP TRIGGER IF EXISTS consent_event_no_truncate ON consent_event;
CREATE TRIGGER consent_event_no_truncate
    BEFORE TRUNCATE ON consent_event
    FOR EACH STATEMENT EXECUTE FUNCTION consent_event_is_append_only();
