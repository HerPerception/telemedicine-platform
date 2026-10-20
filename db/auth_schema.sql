-- ENG-002 — telemedicine-platform authentication, sessions and audit log.
--
-- Scope: the three tables the security layer in `telemedicine/` needs.
--
-- Out of scope (owned by other backlog items, deliberately absent here):
--   * The clinical tables in `db/schema.sql` (ENG-001). This file does not
--     change them. The link between an account and its clinical record is
--     the `account_ref` column that ENG-001 already added to `patient` and
--     `practitioner`; it is an opaque text reference on purpose, so the two
--     features do not depend on each other's table layout.
--   * Email delivery, password reset and multi-factor authentication. The
--     MVP has no mail transport; see docs/auth-design.md.
--   * Rate limiting and lockout policy, which needs a shared cache in front
--     of more than one application instance. The columns that a lockout
--     policy would use (`failed_attempts`, `locked_until`) are present, but
--     nothing writes them yet.
--
-- Conventions (see docs/data-model.md):
--   * UUID v4 primary keys, `timestamptz` for every instant, UTC internally.
--   * Clinical data is never cascade-deleted. Sessions are not clinical data
--     and are cascade-deleted with their account.
--
-- Target: PostgreSQL 13+ (13 provides gen_random_uuid() in core).
-- For PostgreSQL 12 and older, also run: CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- user_account
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_account (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Stored lower-cased by the application; the unique index below is on
    -- lower(email) so that case can never create a second account.
    email               text        NOT NULL,
    -- The encoded form produced by telemedicine.security.hash_password:
    -- pbkdf2_sha256$<iterations>$<salt>$<hash>. The plaintext password is
    -- never stored, logged or emailed.
    password_hash       text        NOT NULL,
    role                text        NOT NULL CHECK (role IN ('patient', 'practitioner')),
    -- The id of the `patient` or `practitioner` row this account belongs to.
    -- Not a foreign key: the clinical tables are owned by ENG-001 and this
    -- file must not constrain them.
    account_ref         text,
    disabled            boolean     NOT NULL DEFAULT false,
    -- Reserved for a future lockout policy; not written by the MVP.
    failed_attempts     integer     NOT NULL DEFAULT 0,
    locked_until        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_account_role_record_ref CHECK (role = 'patient' OR role = 'practitioner'),
    CONSTRAINT user_account_hash_is_encoded CHECK (password_hash LIKE 'pbkdf2_sha256$%')
);

CREATE UNIQUE INDEX IF NOT EXISTS user_account_email_lower_key ON user_account (lower(email));
CREATE INDEX IF NOT EXISTS user_account_account_ref ON user_account (account_ref);

-- ---------------------------------------------------------------------------
-- auth_session
-- ---------------------------------------------------------------------------
-- A session token is shown to the client exactly once. Only its SHA-256
-- digest is stored, so a leaked table cannot be used to impersonate a user.
CREATE TABLE IF NOT EXISTS auth_session (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid        NOT NULL REFERENCES user_account (id) ON DELETE CASCADE,
    token_hash      char(64)    NOT NULL UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    last_seen_at    timestamptz,
    client_ip       inet,
    user_agent      text,
    CONSTRAINT auth_session_expiry_after_creation CHECK (expires_at > created_at),
    CONSTRAINT auth_session_revocation_has_time CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX IF NOT EXISTS auth_session_user_active ON auth_session (user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS auth_session_expiry ON auth_session (expires_at) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- audit_log
-- ---------------------------------------------------------------------------
-- The append-only, tamper-evident log. Every entry carries the hash of the
-- entry before it and its own hash over its content and that link, exactly
-- as computed by telemedicine.audit.hash_payload. Altering or removing an
-- entry breaks the chain from that point on, which
-- telemedicine.audit.AuditLog.verify_chain reports.
--
-- The application writes entries with the previous entry's hash as
-- `previous_hash`; it reads the chain head inside a transaction that takes
-- an advisory lock, so two concurrent writers cannot fork the chain.
CREATE TABLE IF NOT EXISTS audit_log (
    sequence       bigserial   PRIMARY KEY,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    -- Nullable: a failed login for an account that does not exist has no
    -- actor, so the column is null in that case. The application writes no
    -- id rather than a placeholder, because the column is a uuid.
    actor_user_id  uuid,
    actor_role     text,
    action         text        NOT NULL,
    resource_type  text        NOT NULL,
    resource_id    text        NOT NULL,
    outcome        text        NOT NULL CHECK (outcome IN ('success', 'denied', 'error')),
    detail         text        NOT NULL DEFAULT '',
    previous_hash  char(64)    NOT NULL,
    entry_hash     char(64)    NOT NULL UNIQUE,
    CONSTRAINT audit_log_previous_hash_shape CHECK (previous_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT audit_log_entry_hash_shape CHECK (entry_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS audit_log_resource ON audit_log (resource_type, resource_id, sequence);
CREATE INDEX IF NOT EXISTS audit_log_actor ON audit_log (actor_user_id, sequence);
CREATE INDEX IF NOT EXISTS audit_log_occurred ON audit_log (occurred_at);
CREATE INDEX IF NOT EXISTS audit_log_denied ON audit_log (outcome, occurred_at) WHERE outcome = 'denied';

-- The log is append-only. A row that has been written cannot be changed or
-- removed, not even by a privileged session, and the application has no
-- code path that would try.
CREATE OR REPLACE FUNCTION audit_log_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS audit_log_no_update_or_delete ON audit_log;
CREATE TRIGGER audit_log_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_is_append_only();

-- ---------------------------------------------------------------------------
-- Reading the chain back
-- ---------------------------------------------------------------------------
-- The application reconstructs the log for verification with:
--
--   SELECT * FROM audit_log ORDER BY sequence;
--
-- and checks the chain by recomputing each entry hash. The chain head is:
--
--   SELECT entry_hash FROM audit_log ORDER BY sequence DESC LIMIT 1;
--
-- Both must run inside a transaction holding the same advisory lock
-- (pg_advisory_xact_lock) that the insert path uses, otherwise a writer could
-- append between the two statements.
--
-- Retention: entries are never deleted, so the log grows without bound. The
-- retention period required by the privacy gate is an OPS-001 decision; until
-- it is made, nothing purges this table. Archiving to cold storage must
-- preserve the chain, or the archived segment must record the hash the
-- archive starts from.
