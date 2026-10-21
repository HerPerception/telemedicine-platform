-- ENG-018 — the log of transfers of patient data out of Nigeria.
--
-- Scope: the table the cross-border guard writes to.
--
-- Section 41(2) of the Nigeria Data Protection Act 2023: the controller
-- "shall record the basis for transfer of personal data to another country".
-- This table is that record: what was sent, where it went, on what basis,
-- with what justification, and whose data it was.
--
-- Conventions (see docs/data-model.md):
--   * UUID v4 primary keys, `timestamptz` for every instant, UTC internally.
--
-- Target: PostgreSQL 13+.

-- ---------------------------------------------------------------------------
-- transfer_logs
-- ---------------------------------------------------------------------------
-- One row per transfer that happened. A transfer that was refused never
-- reaches this table: there is nothing to record about something that did
-- not occur.
CREATE TABLE IF NOT EXISTS transfer_logs (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- When it happened.
    occurred_at         timestamptz NOT NULL DEFAULT now(),
    -- The service it went to, as it is named in the configuration.
    service             text        NOT NULL DEFAULT '',
    -- The host it went to.
    destination         text        NOT NULL,
    -- The country that host is in.
    destination_country text        NOT NULL,
    -- Who it was for: the address a message was sent to, or the service.
    recipient           text        NOT NULL DEFAULT '',
    -- What kind of data went: health data, a message, a prescription.
    data_categories     text[]      NOT NULL DEFAULT '{}',
    -- The basis in section 43: consent, contract, vital interest, public
    -- interest or legal claim.
    lawful_basis        text
                                CHECK (lawful_basis IS NULL OR lawful_basis IN (
                                    'consent', 'contract', 'vital_interest',
                                    'public_interest', 'legal_claim')),
    -- Why it was allowed, in the practice's own words. A transfer without a
    -- justification is a transfer nobody can explain.
    justification       text        NOT NULL CHECK (justification <> ''),
    -- Whose data it was: the account the data was about.
    user_id             uuid
);

CREATE INDEX IF NOT EXISTS transfer_logs_occurred ON transfer_logs (occurred_at);
CREATE INDEX IF NOT EXISTS transfer_logs_destination ON transfer_logs (destination);
CREATE INDEX IF NOT EXISTS transfer_logs_user ON transfer_logs (user_id);

-- The rows are written once. A transfer that could be edited afterwards
-- would not be a record of the transfer.
CREATE OR REPLACE FUNCTION transfer_logs_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'transfer_logs is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS transfer_logs_no_update_or_delete ON transfer_logs;
CREATE TRIGGER transfer_logs_no_update_or_delete
    BEFORE UPDATE OR DELETE ON transfer_logs
    FOR EACH ROW EXECUTE FUNCTION transfer_logs_is_append_only();

DROP TRIGGER IF EXISTS transfer_logs_no_truncate ON transfer_logs;
CREATE TRIGGER transfer_logs_no_truncate
    BEFORE TRUNCATE ON transfer_logs
    FOR EACH STATEMENT EXECUTE FUNCTION transfer_logs_is_append_only();
