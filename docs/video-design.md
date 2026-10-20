# Video consultation rooms — design

- **Feature:** `ENG-004` — integrate appointment-scoped video consultation rooms
- **Status:** Implemented and tested. The room, the waiting room, the admission control and the join
  tokens are implemented and proven; **the media transport itself is not**, because the MVP has no
  media provider (§7).
- **Owner:** `OpenCode-20261020-3dafd2c8`

## 1. Acceptance criteria

The backlog item is: *"only the booked patient and clinician can join; room unavailable outside the
appointment window; clear retry on join failure."* The README adds a waiting room and clinician
admission control.

| Criterion | Where | Evidence |
| --- | --- | --- |
| Only the booked patient and clinician can join | `telemedicine/video.py`, `VideoService.join` and `_require_participant`; the rule table gains `Action.JOIN` | `tests/test_video.py::JoiningTest::test_only_the_booked_patient_and_the_clinician_may_join`, `::test_a_stranger_cannot_join` |
| The room is unavailable outside the appointment window | `VideoService.join` against the room's window, with a grace period either side | `tests/test_video.py::WindowTest` (6 tests) |
| A join failure surfaces a clear error and a retry path | `JoinUnavailable` with a machine-readable `reason`, a `retryable` flag and `retry_after_seconds`; the HTTP shape in `telemedicine/video_api.py` | `tests/test_video.py::WindowTest`, `tests/test_video_api.py::VideoApiTest::test_joining_before_the_window_is_a_conflict_with_a_retry_path` |
| A waiting room with clinician admission control | `VideoService.join` (the patient waits) and `VideoService.admit` (the clinician admits) | `tests/test_video.py::JoiningTest::test_the_clinician_admits_the_patient` |
| Both parties join from a browser | The HTTP surface under `/video`, and the join token the browser presents to the provider | `tests/test_video_api.py::VideoOverHttpTest` |

## 2. The room

A room is bound to one appointment. It exists for the length of that appointment and for nothing
else: the patient and the clinician of that appointment are the only people who can ever be in it.

| Property | Value |
| --- | --- |
| Bound to | one `Appointment`, and therefore to one patient and one practitioner |
| Window | the appointment's own start and end, plus a grace period either side |
| Open to | the booked patient and the delivering clinician, and nobody else |
| Admitted by | the clinician, who opens the room and admits the patient from the waiting room |
| Credential | a join token, signed per room, valid for five minutes |

The grace period is fifteen minutes before the appointment and ten minutes after it. Before that a
join is refused with a reason and a hint about when to try again; after it the consultation is over
and the refusal is final.

## 3. The waiting room

The patient does not walk straight into the consultation. Joining puts them in the waiting room,
and the clinician admits them:

```
patient joins  ──▶  waiting  ──▶ (clinician admits)  ──▶  admitted  ──▶ join token
```

The clinician joins directly — they are the one who admits — and sees who is waiting. The patient
sees only their own state, and never who else is in the room. A patient cannot admit themselves, and
a clinician who does not deliver the appointment cannot admit anyone.

The rules are the ones of ENG-002's table, with one addition: `Action.JOIN`, with a rule for each
role. The rules stay fail-closed — taking part in a consultation is neither reading a record nor
changing one, so it gets its own action rather than borrowing `READ`.

## 4. The join token

The client does not get to talk to the media provider directly. It gets a token, and presents that:

```
base64url(payload) . base64url(HMAC-SHA256(payload, room_secret))
```

The payload carries the room, the participant, an expiry and a nonce. The secret is generated per
room and never leaves the server. That gives three things:

- a token cannot be used for another room, because it is signed with that room's secret;
- a token cannot be used by another participant, because the participant is in the payload;
- a token stops working after five minutes, so a leaked one is short-lived.

`VideoService.verify_join_token` checks the signature, the expiry and the room. That is the check
the media provider's edge would make — or the client would make before it presents the token.

A token that is admitted and then expires **during** the consultation is a real case: the client
asks for a new one and rejoins. There is no refresh token, and no session that survives the
provider closing the room.

## 5. The retry contract

A client that cannot join always gets the same shape, so that it never has to guess:

```json
{
  "error": "room_not_open_yet",
  "message": "the consultation room opens 15 minutes before the appointment",
  "retryable": true,
  "retry_after_seconds": 412
}
```

| `error` | `retryable` | What the client does |
| --- | --- | --- |
| `room_not_open_yet` | yes | wait `retry_after_seconds`, then try again |
| `consultation_ended` | no | the consultation is over; show the contact details |
| `not_admitted` | yes | poll every `retry_after_seconds` until the clinician admits |
| `login` | — | the session has expired; sign in again |
| `forbidden` | — | the caller is not in this room |
| `not_found` | — | there is no such room |

The HTTP statuses are `400` for a malformed request, `401` for no session, `403` for a caller who is
not in the room, `404` for a room or an appointment that is not there, `405` for an unsupported
method, and `409` for a room that cannot be joined yet — with the reason and the retry path in the
body. A `409` says "not yet", not "you are wrong".

## 6. The media transport

`MediaTransport` is the seam where a provider goes:

```python
class MediaTransport:
    def create_room(self, room) -> str: ...    # the provider's room id
    def close_room(self, room) -> None: ...
    def revoke(self, room, user_id) -> None: ...
```

The implementation here is a loopback: it exists so that the rules above can be tested, and it
returns the room's own id. **It carries no media.** There is no signalling, no TURN, no vendor
account, no codec negotiation and no network.

What a real adapter has to do:

1. create the room with the provider when the room is opened, and keep the provider's room id;
2. accept the join token as the credential of a participant, and verify it the way
   `verify_join_token` does — the provider's edge needs the same secret, or the check has to happen
   before the client reaches the provider;
3. close the room when the appointment's window has passed;
4. tell the client, through a webhook or a poll, that the other side has arrived or left.

## 7. Amendments to earlier features

Recorded in `multi-agent-orchestrator/resolution.md`.

| File | Amendment | Why |
| --- | --- | --- |
| `telemedicine/authorization.py` | `Action.JOIN` and two rules: a patient may join the appointment they booked, a clinician the one they deliver | Taking part in a consultation is its own action, and the rules stay fail-closed |
| `telemedicine/records.py` | `get_appointment`, which returns an appointment without auditing it | The video service needs the window and the participants of the appointment; reading it *for a user* still goes through the audited path |
| `telemedicine/errors.py` | `NotFoundError` | A room that is not there is a 404, not a malformed request |
| `telemedicine/fhir/server.py` | The server can serve several applications under different path prefixes | The FHIR API and the video rooms are different surfaces with different error shapes; one server serves both |

## 8. Known gaps

1. **There is no media.** The transport is a loopback. Nothing in this feature carries a video
   stream, and the join token is a credential for a provider that does not exist yet. This is the
   one gap that stops the feature being a consultation rather than the administration of one.
2. **The room is opened by the clinician.** A patient who arrives early finds no room until the
   clinician opens it. The MVP could open the room when the appointment is booked, which is a small
   change to ENG-003, and that is probably the right answer.
3. **No reconnection.** A token that expires mid-consultation means the client rejoins; there is no
   session to resume, and no record of who was in the room.
4. **No recording, and no policy about it.** Recording a consultation is a significant privacy
   question — consent, retention, who may replay it — and the MVP does not do it. It is not
   recorded in the model either, which is deliberate for now and is not a decision.
5. **No chat, no screen sharing, no device tests.** The browser is expected to handle the media
   itself; this layer has no opinion about it.
6. **The room is in memory.** A restart loses the open rooms and the waiting participants, exactly
   as it loses the sessions (§6 of the compliance review).
7. **The appointment's window is the whole of the admission logic.** A consultation that runs over
   is still admissible within the grace period, and one that ends early is not closed early — there
   is no way to end a room before the appointment's end.
8. **Single clinician.** A room has one patient and one practitioner, which is the MVP. A
   supervisor, an interpreter or a second clinician would need more.
9. **No notification.** Nothing tells the patient that the room is open, or that the clinician has
   arrived. That is the same missing transport as the booking confirmation.
10. **The patient is not identified to the provider beyond the token.** The provider knows a
    participant id, not that they are a patient.

## 9. What the successor needs

- **A media provider adapter** (§6), and a decision about which one — that choice has a privacy
  dimension, because a third-party media provider is a processor of health data.
- **The notification transport**, which the booking confirmation also needs.
- **The recording policy**, before recording is ever switched on.
- **A client**, which has to present the token, poll for admission and handle the retry contract.
- **OPS-001's Group 1**, which applies here too: the rooms hold health data in transit, so TLS and
  the retention of any server-side room state are the same obligations as everywhere else.
