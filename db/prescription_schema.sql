-- ENG-005 — telemedicine-platform prescription documents.
--
-- Scope: the table that holds the metadata of the downloadable document of
-- a prescription. The clinical content of the prescription itself is in the
-- `medication_request` table of ENG-001 (`db/schema.sql`), which this file
-- does not change.
--
-- Out of scope (owned by other backlog items, deliberately absent here):
--   * The bytes of the document. The architecture proposes encrypted object
--     storage; the MVP has no object store, so only the metadata and a
--     storage key are modelled here. The `storage_key` column is what a
--     deployment would fill in with the key of the object in that store.
--   * Encryption at rest and the key management around it, which are OPS-001
--     work and cannot be validated here.
--
-- Conventions (see docs/data-model.md):
--   * UUID v4 primary keys, `timestamptz` for every instant, UTC internally.
--   * Clinical data is never cascade-deleted: a prescription document is
--     part of the clinical record, so it goes with RESTRICT.
--
-- Target: PostgreSQL 13+ (13 provides gen_random_uuid() in core).

-- ---------------------------------------------------------------------------
-- prescription_document
-- ---------------------------------------------------------------------------
-- The document of a prescription: the printable PDF the patient downloads.
-- One document per prescription — the document is the record of what was
-- issued and is never rewritten, so a later status change does not alter
-- it. That is deliberate: a prescription that has been printed and handed
-- to a pharmacy must not be able to change afterwards.
CREATE TABLE prescription_document (
    id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    medication_request_id uuid        NOT NULL UNIQUE
                                     REFERENCES medication_request (id) ON DELETE RESTRICT,
    -- The key of the object in the document store. The MVP has no object
    -- store, so this is where the bytes would live in a deployment.
    storage_key           text        NOT NULL,
    -- The media type of the document; 'application/pdf' for the renderer in
    -- telemedicine.prescriptions.
    content_type          text        NOT NULL DEFAULT 'application/pdf',
    -- The SHA-256 of the document bytes, in lower-case hex. A download that
    -- does not match this checksum is refused rather than served.
    checksum              char(64)    NOT NULL,
    byte_size             integer     NOT NULL CHECK (byte_size > 0),
    -- The status the prescription had when the document was rendered. The
    -- document is a snapshot; this makes that explicit.
    rendered_from_status  text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT prescription_document_checksum_shape
        CHECK (checksum ~ '^[0-9a-f]{64}$'),
    CONSTRAINT prescription_document_content_type
        CHECK (content_type <> ''),
    CONSTRAINT prescription_document_storage_key
        CHECK (storage_key <> '')
);

CREATE INDEX prescription_document_created ON prescription_document (created_at);

-- The document is written once. A change to an existing document is refused
-- by the trigger below, in the same way the audit log is append-only: a
-- prescription document that could be edited after the fact would not be a
-- record of anything.
CREATE OR REPLACE FUNCTION prescription_document_is_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'prescription_document rows are immutable: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER prescription_document_no_update
    BEFORE UPDATE ON prescription_document
    FOR EACH ROW EXECUTE FUNCTION prescription_document_is_immutable();

-- ---------------------------------------------------------------------------
-- Reading the document back
-- ---------------------------------------------------------------------------
-- The application resolves a prescription to its document with:
--
--   SELECT * FROM prescription_document
--    WHERE medication_request_id = $1;
--
-- and verifies the bytes it fetched from the store against `checksum`
-- before serving a download. A mismatch is refused and audited, never
-- served.
--
-- Retention: documents are never deleted, so that the record of what was
-- prescribed survives. The retention period required by the privacy gate is
-- an OPS-001 decision; until it is made, nothing purges this table.
