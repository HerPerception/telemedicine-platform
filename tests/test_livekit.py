"""Tests for the media-server token and the endpoint that issues it.

The media server is the practice's own, in Nigeria, and the token is the
only way into a consultation. These tests hold three things to that:

* the token is in the shape the LiveKit server verifies — HS256, the issuer
  is the API key, the subject is the identity, the expiration is there, and
  the video grant names the room;
* only the booked patient and the clinician who delivers the appointment
  can have one;
* **a consultation is not recorded without the patient's consent**, and when
  the recording is on and the consent is missing, no token is issued at all.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.livekit import (
    DEFAULT_TTL_SECONDS,
    ROOM_PREFIX,
    TokenError,
    issue_access_token,
    room_name,
    verify_access_token,
)

API_KEY = "the-api-key"
API_SECRET = "the-api-secret-a-long-one"
NOW = 1792600000


class TheTokenTest(unittest.TestCase):
    """The token, and the shape the LiveKit server verifies."""

    def token(self, **overrides):
        arguments = {
            "api_key": API_KEY,
            "api_secret": API_SECRET,
            "identity": "user-patient",
            "room": room_name("123"),
        }
        arguments.update(overrides)
        return issue_access_token(**arguments)

    def claims(self, token=None, **overrides):
        return verify_access_token(API_KEY, API_SECRET, token or self.token(**overrides),
                                   now=NOW)

    def test_the_header_says_hs256(self):
        header = json.loads(self._part(self.token(), 0))
        self.assertEqual(header["alg"], "HS256")
        self.assertEqual(header["typ"], "JWT")

    def test_the_issuer_is_the_api_key(self):
        self.assertEqual(self.claims()["iss"], API_KEY)

    def test_the_subject_is_the_identity(self):
        self.assertEqual(self.claims()["sub"], "user-patient")

    def test_the_expiration_is_two_hours(self):
        claims = self.claims()
        self.assertEqual(claims["exp"] - claims["iat"], 2 * 60 * 60)
        self.assertEqual(DEFAULT_TTL_SECONDS, 2 * 60 * 60)

    def test_the_room_is_named_after_the_consultation(self):
        self.assertEqual(self.claims()["video"]["room"], "consultation_123")
        self.assertEqual(ROOM_PREFIX, "consultation_")

    def test_the_grant_allows_publishing_and_subscribing(self):
        video = self.claims()["video"]
        self.assertTrue(video["canPublish"])
        self.assertTrue(video["canSubscribe"])
        self.assertTrue(video["roomJoin"])
        self.assertFalse(video["roomCreate"])

    def test_the_token_carries_nothing_about_the_consultation(self):
        # It is not encrypted: anybody holding it can read it. So it holds
        # an identity, a room and a lifetime, and nothing else.
        payload = json.loads(self._part(self.token(), 1))
        self.assertEqual(set(payload) - {"iss", "sub", "iat", "nbf", "exp",
                                         "identity", "video"},
                         set())
        self.assertNotIn("name", payload)
        self.assertNotIn("notes", payload)

    def test_the_signature_verifies(self):
        self.assertTrue(self.claims())

    def test_a_token_signed_with_another_secret_is_refused(self):
        token = self.token(api_secret="another-secret")
        with self.assertRaises(TokenError):
            verify_access_token(API_KEY, API_SECRET, token, now=NOW)

    def test_a_token_for_another_key_is_refused(self):
        token = self.token(api_key="another-key")
        with self.assertRaises(TokenError):
            verify_access_token(API_KEY, API_SECRET, token, now=NOW)

    def test_an_expired_token_is_refused(self):
        token = self.token(now=NOW)
        with self.assertRaises(TokenError):
            verify_access_token(API_KEY, API_SECRET, token, now=NOW + 2 * 60 * 60 + 1)

    def test_a_token_that_never_expires_is_refused(self):
        # The LiveKit server refuses a token without an expiration, so that
        # a hand-rolled minter cannot mint a permanent credential. This one
        # is signed properly, so that it is the missing expiration that is
        # caught and not the signature.
        import hashlib
        import hmac
        token = self.token()
        header, _payload, _signature = token.split(".")
        claims = json.loads(self._part(token, 1))
        del claims["exp"]
        payload = self._b64(json.dumps(claims, separators=(",", ":"),
                                       sort_keys=True).encode("utf-8"))
        signing_input = f"{header}.{payload}"
        signature = hmac.new(API_SECRET.encode("utf-8"),
                             signing_input.encode("utf-8"), hashlib.sha256).digest()
        forged = f"{signing_input}.{self._b64(signature)}"
        with self.assertRaises(TokenError) as caught:
            verify_access_token(API_KEY, API_SECRET, forged, now=NOW)
        self.assertIn("never expires", str(caught.exception))

    def test_a_token_without_a_key_is_refused(self):
        with self.assertRaises(TokenError):
            self.token(api_key="", api_secret=API_SECRET)
        with self.assertRaises(TokenError):
            self.token(api_key=API_KEY, api_secret="")

    def test_a_token_without_an_identity_is_refused(self):
        with self.assertRaises(TokenError):
            self.token(identity="")

    def test_the_room_needs_an_id(self):
        with self.assertRaises(TokenError):
            room_name("")

    @staticmethod
    def _part(token, index):
        import base64
        part = token.split(".")[index]
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8")

    @staticmethod
    def _b64(raw):
        import base64
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class TheVideoTokenEndpointTest(unittest.TestCase):
    """The endpoint, and who may have a token."""

    def setUp(self):
        from telemedicine.audit import AuditLog
        from telemedicine.auth import AuthService
        from telemedicine.booking import BookingService, SlotService
        from telemedicine.consent import ConsentService
        from telemedicine.models import Role
        from telemedicine.records import (
            PatientRecord,
            PractitionerRecord,
            RecordsService,
        )
        from telemedicine.video import MediaConfiguration, VideoService
        from telemedicine.video_api import VideoApplication

        self.clock = _Clock()
        self.audit = AuditLog(clock=self.clock)
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit, clock=self.clock)
        self.booking = BookingService(self.slots, audit=self.audit,
                                      records=self.records, clock=self.clock)
        self.auth = AuthService(audit=self.audit, password_iterations=1000,
                                clock=self.clock)
        self.consents = ConsentService(audit=self.audit, clock=self.clock)
        self.service = VideoService(self.records, audit=self.audit, clock=self.clock,
                                    media=MediaConfiguration(
                                        host="video.example.ng",
                                        url="wss://video.example.ng",
                                        api_key=API_KEY,
                                        api_secret=API_SECRET),
                                    consents=self.consents)
        self.application = VideoApplication(self.service, self.auth)

        self.patient = self.auth.register("ada@example.org", "a-long-passphrase",
                                          Role.PATIENT, record_id="patient-1")
        self.practitioner = self.auth.register("dr@example.org", "a-long-passphrase",
                                               Role.PRACTITIONER,
                                               record_id="practitioner-1")
        self.stranger = self.auth.register("nobody@example.org", "a-long-passphrase",
                                           Role.PATIENT, record_id="patient-2")
        self.records.add_patient(PatientRecord(
            patient_id="patient-1", user_id=self.patient.user_id,
            display_name="Ada Nwosu Okonkwo"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-1", user_id=self.practitioner.user_id,
            display_name="Dr. Elena Ramirez"))
        self.slot = self.slots.create_slot(
            self.practitioner, practitioner_id="practitioner-1",
            local_start=_tomorrow_at(14), local_end=_tomorrow_at(14, 30),
            timezone_name="Europe/Berlin")
        self.appointment = self.booking.book(self.patient, self.slot.slot_id)

    def call(self, method, path, account=None, body=None):
        headers = {}
        if account is not None:
            token, _session = self.auth.create_session(account)
            headers["authorization"] = f"Bearer {token}"
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        return self.application.handle(method, path, {}, headers, payload)

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    # -- who may have one -------------------------------------------------

    def test_the_patient_may_have_a_token(self):
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.patient)
        self.assertEqual(response.status, 201)
        body = self.payload(response)
        self.assertEqual(body["room"],
                         "consultation_" + self.appointment.appointment_id)
        self.assertEqual(body["url"], "wss://video.example.ng")
        self.assertEqual(body["identity"], self.patient.user_id)
        self.assertTrue(body["can_publish"])
        self.assertTrue(body["can_subscribe"])
        self.assertEqual(body["expires_in"], 2 * 60 * 60)

    def test_the_clinician_may_have_a_token(self):
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.practitioner)
        self.assertEqual(response.status, 201)

    def test_a_stranger_may_not(self):
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.stranger)
        self.assertEqual(response.status, 403)

    def test_a_call_without_a_session_is_refused(self):
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token")
        self.assertEqual(response.status, 401)

    def test_the_token_verifies(self):
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.patient)
        claims = verify_access_token(API_KEY, API_SECRET,
                                     self.payload(response)["token"],
                                     now=int(self.clock().timestamp()))
        self.assertEqual(claims["video"]["room"],
                         "consultation_" + self.appointment.appointment_id)

    def test_the_token_is_audited(self):
        self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token", self.patient)
        from telemedicine.video import ACTION_TOKEN
        entries = [entry for entry in self.audit.entries
                   if entry.action == ACTION_TOKEN and entry.outcome == "success"]
        self.assertTrue(entries)

    def test_a_refused_token_is_audited_as_refused(self):
        self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token", self.stranger)
        from telemedicine.video import ACTION_TOKEN
        refusals = [entry for entry in self.audit.entries
                    if entry.action == ACTION_TOKEN and entry.outcome == "denied"]
        self.assertTrue(refusals)

    # -- the recording ----------------------------------------------------

    def test_the_recording_is_off_by_default(self):
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.patient)
        self.assertFalse(self.payload(response)["recording"])

    def test_a_recording_without_the_consent_is_refused(self):
        self.service.media = _with_recording(self.service.media, enabled=True)
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.patient)
        self.assertEqual(response.status, 403)
        self.assertIn("consented", self.payload(response)["message"])

    def test_the_clinician_cannot_record_it_without_the_consent_either(self):
        self.service.media = _with_recording(self.service.media, enabled=True)
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.practitioner)
        self.assertEqual(response.status, 403)

    def test_a_recording_with_the_consent_is_allowed(self):
        from telemedicine.consent import PURPOSE_CONSULTATION_RECORDING
        self.consents.grant(self.patient.user_id, PURPOSE_CONSULTATION_RECORDING,
                            "2026-10-21")
        self.service.media = _with_recording(self.service.media, enabled=True)
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.patient)
        self.assertEqual(response.status, 201)
        self.assertTrue(self.payload(response)["recording"])

    def test_the_recording_needs_a_consent_of_its_own(self):
        # The other consents are not a consent to record.
        from telemedicine.consent import PURPOSE_RESEARCH
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, "2026-10-21")
        self.service.media = _with_recording(self.service.media, enabled=True)
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.patient)
        self.assertEqual(response.status, 403)

    def test_without_a_media_server_no_token_is_issued(self):
        from telemedicine.video import MediaConfiguration
        self.service.media = MediaConfiguration()
        response = self.call("POST", "/video/consultations/" + self.appointment.appointment_id + "/video-token",
                             self.patient)
        self.assertEqual(response.status, 409)


def _tomorrow_at(hour: int, minute: int = 0):
    """A moment in the future, on the whole minute.

    A slot in the past cannot be booked, and a slot has to start on a whole
    minute, so the test computes one from the clock rather than writing it
    down.
    """
    moment = datetime.now() + timedelta(days=1)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)


class _Clock:
    def __init__(self, start=None):
        self.now = start or datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def _with_recording(media, enabled):
    from dataclasses import replace
    return replace(media, recording_enabled=enabled)


if __name__ == "__main__":
    unittest.main()
