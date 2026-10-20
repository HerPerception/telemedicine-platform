# Notifications — design

- **Feature:** `ENG-011` — the notification outbox: confirmations queued durably for both parties
- **Status:** Implemented and tested. The queue is in the database; the delivery is a seam.
- **Owner:** `OpenCode-20261020-3dafd2c8`

## 1. The problem

The README's acceptance criteria for booking include that **both parties receive a confirmation**,
and the review of the project found the same thing in the gaps of ENG-003: "nothing tells the
patient that the room is open".

The MVP has no mail server, and no SMS provider, and no transport of any kind. That is a fact about
the environment, not an excuse. What can be built honestly is the half that matters and that the
application is responsible for: **deciding that a message is owed, and making sure it cannot be
lost.**

## 2. The outbox

A message is written to the `notification_outbox` table when the thing happens — the booking, the
reschedule, the cancellation, the prescription — and something else sends it afterwards. This is the
outbox pattern, and the reason for it is simple: a booking and its confirmation are either both
there or neither. If the application sent the mail inline, a crash between the two would leave a
patient with a booking nobody told them about. If it queued the message and a separate process
sent it, the queue is in the database and survives the crash.

The delivery process claims a message with `FOR UPDATE SKIP LOCKED`, so two of them can run at once
without sending the same message twice.

## 3. What is queued

| Kind | When | To |
| --- | --- | --- |
| `appointment.booked` | a slot is booked | the patient and the clinician |
| `appointment.rescheduled` | an appointment is moved | the patient and the clinician |
| `appointment.cancelled` | an appointment is cancelled | the patient and the clinician |
| `prescription.issued` | a prescription is issued | the patient |

The patient and the clinician are told different things: the patient is told *their* appointment
has been booked, the clinician that an appointment *has been booked for one of their patients*. A
message that says the same thing to both is a message that says the wrong thing to one of them.

The times in a message are in UTC, and the zone is spelled out — "2026-10-21 at 12:00 UTC" — because
the recipient is somewhere else and a bare time is ambiguous. Rendering it in the recipient's own
zone is the client's business.

## 4. The transport

`NotificationTransport` is the seam:

```python
class NotificationTransport:
    def send(self, notification: Notification) -> None:
        """Send one message. Raise to say it could not be sent."""
```

The implementation in the repository records what would have been sent, which is what the tests read
and what a demo shows. A deployment supplies one that talks to a mail server.

**A message that cannot be sent is not lost.** It stays queued with the error recorded, and the
next pass tries again — until it has been tried `MAX_ATTEMPTS` (five) times, when it is marked
`failed` and somebody has to look at it. A message that fails for ever must not be retried for
ever, and must not be quietly dropped either.

## 5. The amendments this needed

Two of them were found by the database, and both are the same mistake:

- **The audit log's actor column is a `uuid`**, and the system actions wrote the string `"system"`
  into it. An action that was not performed by an account has no account, so the actor is now
  `None` — exactly as it is for a login against an address that has no account. The role stays
  `"system"`, which is a string column.
- **The outbox's recipient is an account**, so its id is a `uuid`. The tests had to use real ones.

Neither was found by reading the code. Both were found by writing to a real server, which is the
argument for having one.

## 6. Known gaps

1. **No transport.** The application queues; something else must send. The MVP has no mail server,
   so a booking still tells nobody in practice.
2. **No reminders.** A patient is told about a booking, and not reminded of it. Reminders are a
   policy question — how long before, how many — and are not in the MVP's scope.
3. **The queue is not drained by anything.** There is no delivery process, no cron, no worker. The
   `deliver()` method exists and is tested; something has to call it.
4. **The recipient's address is not in the message.** The message names the account, and the
   transport has to look the address up. That is deliberate: the address is personal data, and
   putting it in a notification row would put it in a second place.
5. **The times are in UTC**, not in the recipient's zone. The client renders them.
6. **No delivery report for the practice.** A practice that wants to know "did the patient get the
   message" has to look at the outbox.
7. **The rows are never deleted.** A record of what the practice told a patient is part of the
   clinical record; the retention question is the same one as for the audit log, and OPS-001 owns it.

## 7. What the successor needs

- **A transport** — a mail server, and a decision about which one and what it means for the
  practice's data.
- **Something that drains the queue**: a worker, a cron, or a request that does it.
- **Reminders**, when the practice wants them.
- The rest of the notification types the practice will want: a request for a new password, an
  invitation, a message from the clinician to the patient between visits.
