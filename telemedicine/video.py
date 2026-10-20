"""Video consultation rooms.

This is the ENG-004 layer: the room a booked appointment is held in, the
waiting room in front of it, and the admission control that decides who
gets in.

The rules of the MVP, and where each is enforced:

*only the booked patient and clinician can join*
    The join is authorized against the appointment's scope — a patient
    reaches their own appointment, a clinician the ones they deliver — and
    the video service checks the room's own participant list as well.

*the room is unavailable outside the appointment window*
    The window is the appointment's own start and end. A join before the
    window opens or after it closes is refused with a reason and, where it
    makes sense, a hint about when to try again.

*join failures surface a clear error and a retry path*
    Every refusal is a :class:`JoinUnavailable` with a machine-readable
    ``reason``, a ``retryable`` flag and, when it makes sense, a
    ``retry_after_seconds``. The client never has to guess whether to try
    again.

The media transport itself is behind :class:`MediaTransport`. The MVP has no
media provider — there is no signalling server, no TURN, no vendor — so the
transport here is an in-memory loopback that exists to make the rules
testable, and the real adapter is the piece that is left. What the provider
would need from this layer is the join token, which is signed, short-lived
and bound to one room and one participant.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog
from telemedicine.authorization import AccessScope, Action, Authorizer, ResourceType
from telemedicine.errors import AuthorizationError, NotFoundError, ValidationError
from telemedicine.models import Role, UserAccount
from telemedicine.records import Appointment, RecordsService

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

# How long before the appointment a room may be joined, and how long after.
DEFAULT_EARLY_GRACE = timedelta(minutes=15)
DEFAULT_LATE_GRACE = timedelta(minutes=10)

# How long a join token is valid for.
DEFAULT_TOKEN_TTL = timedelta(minutes=5)

# How long the client should wait before polling again.
DEFAULT_POLL_SECONDS = 15

# The states a participant can be in.
PARTICIPANT_WAITING = "waiting"
PARTICIPANT_ADMITTED = "admitted"
PARTICIPANT_DECLINED = "declined"

# The states a room can be in.
ROOM_SCHEDULED = "scheduled"
ROOM_OPEN = "open"
ROOM_CLOSED = "closed"

# Audit actions.
ACTION_ROOM_OPEN = "video.room_open"
ACTION_JOIN = "video.join"
ACTION_ADMIT = "video.admit"
ACTION_TOKEN = "video.join_token"


class JoinUnavailable(ValidationError):
    """A join could not happen, and the client has to be told what to do.

    ``reason`` is a stable, machine-readable code. ``retryable`` says
    whether trying again could work, and ``retry_after_seconds`` says when.
    """

    def __init__(self, reason: str, message: str, *, retryable: bool = False,
                 retry_after_seconds: Optional[int] = None):
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class JoinToken:
    """The credential a client presents to the media provider."""

    token: str
    room_id: str
    user_id: str
    expires_at: datetime

    def expires_in(self, now: datetime) -> int:
        return max(0, int((self.expires_at - now).total_seconds()))


@dataclass(frozen=True)
class JoinResult:
    """What a join attempt produced."""

    room_id: str
    status: str
    admitted: bool
    retryable: bool = False
    retry_after_seconds: Optional[int] = None
    token: Optional[str] = None


@dataclass(frozen=True)
class Room:
    """A consultation room, bound to one appointment."""

    room_id: str
    appointment_id: str
    starts_at: datetime
    ends_at: datetime
    patient_user_id: str
    practitioner_user_id: str
    status: str = ROOM_SCHEDULED
    participants: Tuple[Tuple[str, str], ...] = ()
    secret: bytes = b""
    created_at: Optional[datetime] = None

    def participant_status(self, user_id: str) -> Optional[str]:
        for participant, status in self.participants:
            if participant == user_id:
                return status
        return None

    @property
    def waiting(self) -> Tuple[str, ...]:
        return tuple(participant for participant, status in self.participants
                     if status == PARTICIPANT_WAITING)

    def is_participant(self, user_id: str) -> bool:
        return user_id in (self.patient_user_id, self.practitioner_user_id)


class MediaTransport:
    """The interface a media provider has to satisfy.

    The MVP has no provider. This loopback implementation exists so that the
    rules above can be tested; a real adapter would create the room with the
    provider, close it afterwards, and hand the join token to the client.
    """

    def create_room(self, room: Room) -> str:
        """Create the room with the provider and return its provider id."""
        return f"loopback-{room.room_id}"

    def close_room(self, room: Room) -> None:
        """Close the room with the provider."""
        return None

    def revoke(self, room: Room, user_id: str) -> None:
        """Remove a participant from the provider's room."""
        return None


class VideoService:
    """Rooms, the waiting room, admission control and join tokens."""

    def __init__(self, records: RecordsService, authorizer: Optional[Authorizer] = None,
                 audit: Optional[AuditLog] = None, transport: Optional[MediaTransport] = None,
                 clock=_utc_now, early_grace: timedelta = DEFAULT_EARLY_GRACE,
                 late_grace: timedelta = DEFAULT_LATE_GRACE,
                 token_ttl: timedelta = DEFAULT_TOKEN_TTL):
        self.records = records
        self.authorizer = authorizer if authorizer is not None else Authorizer()
        self.audit = audit if audit is not None else AuditLog(clock=clock)
        self.transport = transport if transport is not None else MediaTransport()
        self._clock = clock
        self.early_grace = early_grace
        self.late_grace = late_grace
        self.token_ttl = token_ttl
        self._rooms: Dict[str, Room] = {}

    # -- opening a room ---------------------------------------------------

    def open_room(self, actor: UserAccount, appointment_id: str) -> Room:
        """Open the room of a booked appointment.

        Only the clinician who delivers the appointment may open it: the
        patient cannot admit themselves, and the room is where the
        admission control happens.
        """
        appointment = self._require_appointment(appointment_id)
        scope = self._appointment_scope(appointment)
        decision = self.authorizer.decide(actor, Action.UPDATE, ResourceType.APPOINTMENT, scope)
        if not decision.allowed:
            self._audit_denied(actor, ACTION_ROOM_OPEN, appointment_id, decision.reason)
            raise AuthorizationError(
                "only the clinician who delivers the appointment may open its room",
                resource_type=ResourceType.APPOINTMENT.value,
                resource_id=appointment_id,
                action=Action.UPDATE.value)
        if actor.role != Role.PRACTITIONER:
            self._audit_denied(actor, ACTION_ROOM_OPEN, appointment_id,
                               "the caller is not a clinician")
            raise AuthorizationError(
                "only the clinician who delivers the appointment may open its room",
                resource_type=ResourceType.APPOINTMENT.value,
                resource_id=appointment_id,
                action=Action.UPDATE.value)

        existing = self._room_for_appointment(appointment_id)
        if existing is not None:
            return existing

        room = Room(
            room_id=str(uuid.uuid4()),
            appointment_id=appointment.appointment_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            patient_user_id=appointment.patient_user_id,
            practitioner_user_id=appointment.practitioner_user_id,
            status=ROOM_SCHEDULED,
            participants=(),
            secret=secrets.token_bytes(32),
            created_at=self._clock(),
        )
        self.transport.create_room(room)
        self._rooms[room.room_id] = room
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_ROOM_OPEN,
            resource_type="video_room",
            resource_id=room.room_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"opened the room of appointment {appointment_id}",
        )
        return room

    # -- joining ----------------------------------------------------------

    def join(self, actor: UserAccount, room_id: str) -> JoinResult:
        """Try to join a room.

        The clinician is admitted as soon as they join. The patient joins
        the waiting room and is admitted by the clinician.
        """
        room = self._require_room(room_id)
        self._require_participant(actor, room)

        now = self._clock()
        if now < room.starts_at - self.early_grace:
            wait = int((room.starts_at - self.early_grace - now).total_seconds())
            self._audit_denied(actor, ACTION_JOIN, room_id, "the room is not open yet")
            raise JoinUnavailable(
                "room_not_open_yet",
                f"the consultation room opens {self.early_grace} before the appointment",
                retryable=True, retry_after_seconds=max(wait, 1))
        if now > room.ends_at + self.late_grace:
            self._audit_denied(actor, ACTION_JOIN, room_id, "the consultation has ended")
            raise JoinUnavailable(
                "consultation_ended",
                "the consultation has ended and the room is closed",
                retryable=False)

        if actor.role == Role.PRACTITIONER:
            room = self._set_participant(room, actor.user_id, PARTICIPANT_ADMITTED)
            self._audit(actor, ACTION_JOIN, room_id, OUTCOME_SUCCESS, "joined the room")
            return JoinResult(room_id=room.room_id, status=room.status, admitted=True)

        # The patient waits for the clinician to admit them.
        if room.participant_status(actor.user_id) != PARTICIPANT_ADMITTED:
            room = self._set_participant(room, actor.user_id, PARTICIPANT_WAITING)
            self._audit(actor, ACTION_JOIN, room_id, OUTCOME_SUCCESS,
                        "waited in the waiting room")
            return JoinResult(
                room_id=room.room_id,
                status=PARTICIPANT_WAITING,
                admitted=False,
                retryable=True,
                retry_after_seconds=DEFAULT_POLL_SECONDS,
            )

        self._audit(actor, ACTION_JOIN, room_id, OUTCOME_SUCCESS, "joined the room")
        return JoinResult(room_id=room.room_id, status=PARTICIPANT_ADMITTED, admitted=True)

    def admit(self, actor: UserAccount, room_id: str, participant_user_id: str) -> Room:
        """Admit a waiting participant. Only the clinician may do this."""
        room = self._require_room(room_id)
        self._require_participant(actor, room)
        if actor.user_id != room.practitioner_user_id:
            self._audit_denied(actor, ACTION_ADMIT, room_id,
                               "only the clinician may admit a participant")
            raise AuthorizationError(
                "only the clinician who delivers the appointment may admit a participant",
                resource_type="video_room", resource_id=room_id, action=Action.UPDATE.value)
        if room.participant_status(participant_user_id) is None:
            raise NotFoundError(f"'{participant_user_id}' is not in this room")
        if room.participant_status(participant_user_id) == PARTICIPANT_ADMITTED:
            return room
        room = self._set_participant(room, participant_user_id, PARTICIPANT_ADMITTED)
        self._audit(actor, ACTION_ADMIT, room_id, OUTCOME_SUCCESS,
                    f"admitted {participant_user_id}")
        return room

    def decline(self, actor: UserAccount, room_id: str, participant_user_id: str) -> Room:
        """Decline a waiting participant."""
        room = self._require_room(room_id)
        self._require_participant(actor, room)
        if actor.user_id != room.practitioner_user_id:
            raise AuthorizationError(
                "only the clinician who delivers the appointment may decline a participant",
                resource_type="video_room", resource_id=room_id, action=Action.UPDATE.value)
        room = self._set_participant(room, participant_user_id, PARTICIPANT_DECLINED)
        self._audit(actor, ACTION_ADMIT, room_id, OUTCOME_SUCCESS,
                    f"declined {participant_user_id}")
        return room

    # -- the state of the room ---------------------------------------------

    def room_state(self, actor: UserAccount, room_id: str) -> dict:
        """What a participant may see of the room.

        The clinician sees who is waiting; the patient sees their own state
        and whether they are admitted.
        """
        room = self._require_room(room_id)
        self._require_participant(actor, room)
        now = self._clock()
        state = {
            "room_id": room.room_id,
            "appointment_id": room.appointment_id,
            "status": self._status_of(room, now),
            "starts_at": _iso(room.starts_at),
            "ends_at": _iso(room.ends_at),
            "your_status": room.participant_status(actor.user_id) or "not_joined",
        }
        if actor.user_id == room.practitioner_user_id:
            state["waiting"] = list(room.waiting)
            state["participants"] = [
                {"user_id": participant, "status": status}
                for participant, status in room.participants
            ]
        return state

    def issue_join_token(self, actor: UserAccount, room_id: str) -> JoinToken:
        """Give an admitted participant the token they present to the provider."""
        room = self._require_room(room_id)
        self._require_participant(actor, room)
        status = room.participant_status(actor.user_id)
        if status != PARTICIPANT_ADMITTED:
            self._audit_denied(actor, ACTION_TOKEN, room_id,
                               "a join token was asked for before admission")
            raise JoinUnavailable(
                "not_admitted",
                "the clinician has not admitted you to the consultation yet",
                retryable=True, retry_after_seconds=DEFAULT_POLL_SECONDS)
        now = self._clock()
        if now < room.starts_at - self.early_grace or now > room.ends_at + self.late_grace:
            raise JoinUnavailable(
                "room_not_open",
                "the consultation room is not open",
                retryable=False)

        expires_at = now + self.token_ttl
        claims = {
            "room": room.room_id,
            "user": actor.user_id,
            "exp": int(expires_at.timestamp()),
            "nonce": secrets.token_urlsafe(8),
        }
        token = self._sign(claims, room.secret)
        self._audit(actor, ACTION_TOKEN, room_id, OUTCOME_SUCCESS,
                    f"issued a join token until {_iso(expires_at)}")
        return JoinToken(token=token, room_id=room.room_id, user_id=actor.user_id,
                         expires_at=expires_at)

    def verify_join_token(self, token: str) -> dict:
        """Check a join token and return its claims.

        This is what the media provider's edge would call, or the client
        would call before it presents the token.
        """
        room_id, claims = self._decode(token)
        room = self._rooms.get(room_id)
        if room is None:
            raise ValidationError("the room of this token does not exist")
        expected = self._sign(claims, room.secret)
        if not hmac.compare_digest(expected, token):
            raise ValidationError("the token is not valid for this room")
        if int(claims.get("exp", 0)) <= int(self._clock().timestamp()):
            raise ValidationError("the token has expired")
        return claims

    # -- internals --------------------------------------------------------

    def _require_appointment(self, appointment_id: str) -> Appointment:
        appointment = self.records.get_appointment(appointment_id)
        if appointment is None:
            raise NotFoundError(f"no appointment with id '{appointment_id}'")
        return appointment

    def _require_room(self, room_id: str) -> Room:
        room = self._rooms.get(room_id)
        if room is None:
            raise NotFoundError(f"no room with id '{room_id}'")
        return room

    def _room_for_appointment(self, appointment_id: str) -> Optional[Room]:
        for room in self._rooms.values():
            if room.appointment_id == appointment_id:
                return room
        return None

    def _require_participant(self, actor: UserAccount, room: Room) -> None:
        """Only the booked patient and the delivering clinician are in the room."""
        if actor.user_id in (room.patient_user_id, room.practitioner_user_id):
            return
        self._audit_denied(actor, ACTION_JOIN, room.room_id,
                           "the caller is not a participant of this room")
        raise AuthorizationError(
            "only the booked patient and the clinician who delivers the appointment may join",
            resource_type="video_room", resource_id=room.room_id, action=Action.JOIN.value)

    def _appointment_scope(self, appointment: Appointment) -> AccessScope:
        return AccessScope(
            owner_user_id=appointment.patient_user_id,
            treating_user_ids=frozenset({appointment.practitioner_user_id}),
        )

    def _set_participant(self, room: Room, user_id: str, status: str) -> Room:
        participants = [(participant, existing) for participant, existing in room.participants
                        if participant != user_id]
        participants.append((user_id, status))
        updated = replace(room, participants=tuple(sorted(participants)),
                          status=ROOM_OPEN if room.status == ROOM_SCHEDULED else room.status)
        self._rooms[room.room_id] = updated
        return updated

    def _status_of(self, room: Room, now: datetime) -> str:
        if now > room.ends_at + self.late_grace:
            return ROOM_CLOSED
        if room.status == ROOM_OPEN:
            return ROOM_OPEN
        return ROOM_SCHEDULED

    def _sign(self, claims: dict, secret: bytes) -> str:
        payload = base64.urlsafe_b64encode(
            json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        payload = payload.rstrip(b"=")
        signature = hmac.new(secret, payload, hashlib.sha256).digest()
        signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
        return f"{payload.decode('ascii')}.{signature.decode('ascii')}"

    def _decode(self, token: str) -> Tuple[str, dict]:
        if not token or "." not in token:
            raise ValidationError("the token is malformed")
        payload, _, _signature = token.partition(".")
        padding = "=" * (-len(payload) % 4)
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + padding).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise ValidationError("the token is malformed") from error
        if not isinstance(claims, dict) or "room" not in claims:
            raise ValidationError("the token is malformed")
        return claims["room"], claims

    def _audit(self, actor: UserAccount, action: str, room_id: str, outcome: str,
               detail: str) -> None:
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=action,
            resource_type="video_room",
            resource_id=room_id,
            outcome=outcome,
            detail=detail,
        )

    def _audit_denied(self, actor: UserAccount, action: str, room_id: str, reason: str) -> None:
        self._audit(actor, action, room_id, OUTCOME_DENIED, f"denied: {reason}")


