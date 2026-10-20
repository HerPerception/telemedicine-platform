-- ENG-011 — the notification outbox.
--
-- Scope: the table that holds the confirmations and reminders the practice
-- sends. A booking has to tell the patient and the clinician that it
-- happened; the MVP has no mail transport, so the application *queues* the
-- message and something else sends it.
--
-- Why a table and not a call to a mail server: a message queued in the
-- database and a message sent by a mail server are not the same thing, and
-- only the first of them survives a crash between the booking and the
-- sending. It is the same outbox pattern as the payment and the e-mail
-- patterns that every system that has to be reliable uses: write the intent
-- in the same transaction as the work, and deliver it afterwards.
--
-- Conventions (see docs/data-model.md):
--   * UUID v4 primary keys, `timestamptz` for every instant, UTC internally.
--   * The rows are a record of what the practice sent, so they are not
--     deleted by the delivery process.

-- ---------------------------------------------------------------------------
-- notification_outbox
-- ---------------------------------------------------------------------------
-- One row per message to send. The row is written when the thing happens —
-- the booking, the cancellation, the prescription — and the delivery process
-- drains the queue.
CREATE TABLE IF NOT EXISTS notification_outbox (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- What the message is about: appointment.booked, appointment.rescheduled,
    -- appointment.cancelled, prescription.issued.
    kind                text        NOT NULL,
    -- The account the message is for.
    recipient_user_id   uuid        NOT NULL,
    -- How it is delivered: email for now. A practice with a phone number
    -- would add sms.
    channel             text        NOT NULL DEFAULT 'email',
    subject             text        NOT NULL,
    body                text        NOT NULL,
    -- queued, sent, or failed. A message that has failed too many times is
    -- failed, and a person has to look at it.
    status              text        NOT NULL DEFAULT 'queued'
                                    CHECK (status IN ('queued', 'sent', 'failed')),
    -- How many times delivery has been attempted.
    attempts            integer     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    -- The last error, so that a failure can be diagnosed.
    last_error          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    sent_at             timestamptz
);

-- The delivery process looks for the queued messages, oldest first.
CREATE INDEX IF NOT EXISTS notification_outbox_pending
    ON notification_outbox (created_at) WHERE status = 'queued';

-- The recipient's own view of what they were told.
CREATE INDEX IF NOT EXISTS notification_outbox_recipient
    ON notification_outbox (recipient_user_id, created_at);

-- ---------------------------------------------------------------------------
-- Reading and writing
-- ---------------------------------------------------------------------------
-- The application writes a row in the same transaction as the booking it
-- belongs to, so that a booking and its confirmation are either both there
-- or neither.
--
-- The delivery process claims a message and sends it:
--
--   SELECT id FROM notification_outbox
--    WHERE status = 'queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED;
--
-- The `SKIP LOCKED` is what lets two delivery processes run at once without
-- sending the same message twice. After the attempt, the row is marked sent,
-- or left queued with the error recorded so that it is tried again, or
-- marked failed when it has been tried too many times.
--
-- The rows are not deleted: a record of what the practice told a patient is
-- part of the clinical record. The retention question is the same one as for
-- the audit log, and the same answer — OPS-001 owns it.
