-- ENG-017 — the retention job: the trash, and the record of every removal.
--
-- Scope: the two tables the retention policy needs.
--
-- Out of scope, and deliberately:
--   * The `deleted_at` columns of the clinical tables, which live in
--     `db/schema.sql` with the tables they belong to.
--   * The audit log, which is a hash chain. The chain links every entry to
--     the one before it and its head is published outside the database, so
--     it cannot be pruned without breaking the chain that makes it worth
--     anything. The retention job reports the entries that are past their
--     period and leaves them where they are.
--
-- Conventions (see docs/data-model.md):
--   * UUID v4 primary keys, `timestamptz` for every instant, UTC internally.
--
-- Target: PostgreSQL 13+.

-- ---------------------------------------------------------------------------
-- deleted_record — the trash
-- ---------------------------------------------------------------------------
-- A record that has been soft-deleted. The whole record is kept here, as
-- JSON, so that it can be put back while the grace period lasts. The live
-- rows are marked with `deleted_at` at the same moment; they are removed
-- only when the grace period has passed.
CREATE TABLE IF NOT EXISTS deleted_record (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- What was deleted: clinical_record, or prescription_document.
    record_type     text        NOT NULL
                                CHECK (record_type IN ('clinical_record',
                                                       'prescription_document')),
    -- The id of the record in its own table.
    record_id       text        NOT NULL,
    -- The patient the record is about, when it is about one.
    patient_id      uuid,
    -- The record itself, as JSON. The whole clinical record: the patient,
    -- their encounters, their prescriptions and their appointments.
    payload         jsonb       NOT NULL,
    -- When it was soft-deleted, and when it may be purged: thirty days
    -- later, so that a record taken out in error can still be put back.
    deleted_at      timestamptz NOT NULL DEFAULT now(),
    purge_after     timestamptz NOT NULL,
    CONSTRAINT deleted_record_purge_after_deleted
        CHECK (purge_after > deleted_at)
);

CREATE INDEX IF NOT EXISTS deleted_record_purge_after ON deleted_record (purge_after);
CREATE INDEX IF NOT EXISTS deleted_record_patient ON deleted_record (patient_id);

-- ---------------------------------------------------------------------------
-- deletion_audit — every removal, and why
-- ---------------------------------------------------------------------------
-- The evidence that the policy was applied, and what it was applied to. It
-- is append-only in the same way the audit log is: a removal that could be
-- edited afterwards would not be a record of anything.
CREATE TABLE IF NOT EXISTS deletion_audit (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    record_type     text        NOT NULL,
    record_id       text        NOT NULL,
    patient_id      uuid,
    -- soft: the record was moved to the trash and marked.
    -- hard: the record was removed for good, after the grace period.
    -- restored: it was put back.
    stage           text        NOT NULL
                                CHECK (stage IN ('soft', 'hard', 'restored')),
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    -- Why it was done. Not empty: a removal without a reason is not
    -- explainable to the person whose record it was.
    reason          text        NOT NULL CHECK (reason <> ''),
    -- Where the policy came from, so that the numbers applied are on the
    -- record of the removal itself.
    policy_source   text        NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS deletion_audit_occurred ON deletion_audit (occurred_at);
CREATE INDEX IF NOT EXISTS deletion_audit_record ON deletion_audit (record_type, record_id);

-- The rows are written once. A change to one, or its removal, is refused.
CREATE OR REPLACE FUNCTION deletion_audit_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'deletion_audit is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS deletion_audit_no_update_or_delete ON deletion_audit;
CREATE TRIGGER deletion_audit_no_update_or_delete
    BEFORE UPDATE OR DELETE ON deletion_audit
    FOR EACH ROW EXECUTE FUNCTION deletion_audit_is_append_only();

DROP TRIGGER IF EXISTS deletion_audit_no_truncate ON deletion_audit;
CREATE TRIGGER deletion_audit_no_truncate
    BEFORE TRUNCATE ON deletion_audit
    FOR EACH STATEMENT EXECUTE FUNCTION deletion_audit_is_append_only();
