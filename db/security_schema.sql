-- ENG-007 — the security state that has to be shared between instances.
--
-- Scope: the table behind the login lockout. The audit log of ENG-002 is
-- already in `db/auth_schema.sql`; this file adds what the lockout needs.
--
-- Why a table and not a counter in the process: a lockout that lives in one
-- application instance is no lockout at all the moment there are two, and
-- the failure it prevents — a password-guessing attack against a clinical
-- system — is exactly the case where an attacker can reach every instance.
--
-- Conventions (see docs/data-model.md):
--   * `timestamptz` for every instant, UTC internally.
--   * The row is a security record: it is updated in place, never deleted.

-- ---------------------------------------------------------------------------
-- auth_lockout
-- ---------------------------------------------------------------------------
-- One row per key that is being counted. The key of the MVP is the
-- normalised email address of the account, whether or not the account
-- exists — an attacker who does not know the addresses must not be able to
-- tell the difference, and a counter that only existed for known accounts
-- would tell them.
CREATE TABLE IF NOT EXISTS auth_lockout (
    -- The normalised email address of the account being counted.
    key             text        PRIMARY KEY,
    -- The number of consecutive failures since the last success.
    failed_attempts integer     NOT NULL DEFAULT 0,
    -- When the lock ends. Null means the key is not locked.
    locked_until    timestamptz,
    -- When the counter was last touched. Kept for the review of a lockout.
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auth_lockout_attempts_not_negative
        CHECK (failed_attempts >= 0)
);

CREATE INDEX IF NOT EXISTS auth_lockout_locked ON auth_lockout (locked_until)
    WHERE locked_until IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Reading and writing
-- ---------------------------------------------------------------------------
-- The application reads and writes one row per attempt:
--
--   SELECT failed_attempts, locked_until FROM auth_lockout WHERE key = $1;
--
-- and takes a row lock on it before it updates, so that two instances
-- counting the same failure at the same time do not lose a count:
--
--   SELECT failed_attempts FROM auth_lockout WHERE key = $1 FOR UPDATE;
--
-- A key that does not exist yet is inserted with the first failure; the
-- insert is retried on a conflict, because two instances may insert the same
-- key at the same moment.
--
-- The rows are not deleted: a key that was locked once stays, with its
-- counter, until a successful login clears it. The retention question for
-- this table is the same one as for the audit log, and the same answer —
-- OPS-001 owns it.
