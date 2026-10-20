"""Tests for the video rooms over HTTP.

The acceptance criteria of ENG-004 are about what a client experiences, so
they are checked over a real socket as well as in process.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from telemedicine.audit import AuditLog
from telemedicine.auth import AuthService
from telemedicine.booking import BookingService, SlotService
from telemedicine.fhir.server import make_server
from telemedicine.models import Role
from telemedicine.records import PatientRecord, PractitionerRecord, RecordsService
from telemedicine.video import VideoService
from telemedicine.video_api import VideoApplication

NOW = datetime(2026, 10, 21, 11, 55, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)
        return self.now


class VideoApiTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.audit = AuditLog(clock=self.clock)
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit, clock=self.clock)
        self.booking = BookingService(self.slots, audit=self.audit, records=self.records,
                                      clock=self.clock)
        self.auth = AuthService(audit=self.audit, password_iterations=1000, clock=self.clock)
        self.service = VideoService(self.records, audit=self.audit, clock=self.clock)
        self.application = VideoApplication(self.service, self.auth)

        self.patient = self.auth.register("ada@example.org", "a-long-passphrase",
                                          Role.PATIENT, record_id="patient-1")
        self.practitioner = self.auth.register("dr@example.org", "a-long-passphrase",
                                               Role.PRACTITIONER, record_id="practitioner-1")
        self.stranger = self.auth.register("nobody@example.org", "a-long-passphrase",
                                           Role.PATIENT, record_id="patient-2")

        self.records.add_patient(PatientRecord(patient_id="patient-1",
                                               user_id=self.patient.user_id,
                                               display_name="Ada Nwosu Okonkwo"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-1", user_id=self.practitioner.user_id,
            display_name="Dr. Elena Ramirez"))

        self.slot = self.slots.create_slot(
            self.practitioner, practitioner_id="practitioner-1",
            local_start=datetime(2026, 10, 21, 14, 0), local_end=datetime(2026, 10, 21, 14, 30),
            timezone_name="Europe/Berlin")
        self.appointment = self.booking.book(self.patient, self.slot.slot_id)

    def token_for(self, account) -> str:
        token, _session = self.auth.create_session(account)
        return token

    def call(self, method, path, token=None, body=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self.application.handle(method, "/video" + path, {}, headers, data or b"")

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def open_room(self):
        return self.call("POST", "/rooms", token=self.token_for(self.practitioner),
                         body={"appointment": self.appointment.appointment_id})


class VideoApiTest(VideoApiTestCase):
    def test_the_clinician_opens_a_room(self):
        response = self.open_room()
        self.assertEqual(response.status, 201)
        payload = self.payload(response)
        self.assertEqual(payload["appointment_id"], self.appointment.appointment_id)
        self.assertEqual(payload["starts_at"], "2026-10-21T12:00:00Z")

    def test_a_request_without_a_token_is_refused(self):
        response = self.call("POST", "/rooms", body={"appointment": self.appointment.appointment_id})
        self.assertEqual(response.status, 401)
        self.assertIn("WWW-Authenticate", response.headers)

    def test_a_patient_cannot_open_a_room(self):
        response = self.call("POST", "/rooms", token=self.token_for(self.patient),
                             body={"appointment": self.appointment.appointment_id})
        self.assertEqual(response.status, 403)

    def test_a_malformed_body_is_refused(self):
        response = self.application.handle("POST", "/video/rooms", {},
                                           {"Authorization": f"Bearer {self.token_for(self.practitioner)}"},
                                           b"{not json")
        self.assertEqual(response.status, 400)

    def test_a_body_without_an_appointment_is_refused(self):
        response = self.call("POST", "/rooms", token=self.token_for(self.practitioner), body={})
        self.assertEqual(response.status, 400)

    def test_a_stranger_cannot_join(self):
        room = self.payload(self.open_room())
        response = self.call("POST", f"/rooms/{room['room_id']}/join",
                             token=self.token_for(self.stranger))
        self.assertEqual(response.status, 403)

    def test_the_patient_joins_into_the_waiting_room(self):
        room = self.payload(self.open_room())
        response = self.call("POST", f"/rooms/{room['room_id']}/join",
                             token=self.token_for(self.patient))
        self.assertEqual(response.status, 200)
        payload = self.payload(response)
        self.assertEqual(payload["status"], "waiting")
        self.assertFalse(payload["admitted"])
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["retry_after_seconds"], 15)

    def test_joining_before_the_window_is_a_conflict_with_a_retry_path(self):
        room = self.payload(self.open_room())
        self.clock.now = NOW - timedelta(minutes=20)
        response = self.call("POST", f"/rooms/{room['room_id']}/join",
                             token=self.token_for(self.patient))
        self.assertEqual(response.status, 409)
        payload = self.payload(response)
        self.assertEqual(payload["error"], "room_not_open_yet")
        self.assertTrue(payload["retryable"])
        self.assertGreater(payload["retry_after_seconds"], 0)

    def test_joining_after_the_consultation_is_a_conflict_that_is_not_retryable(self):
        room = self.payload(self.open_room())
        self.clock.now = NOW + timedelta(hours=1)
        response = self.call("POST", f"/rooms/{room['room_id']}/join",
                             token=self.token_for(self.patient))
        self.assertEqual(response.status, 409)
        payload = self.payload(response)
        self.assertEqual(payload["error"], "consultation_ended")
        self.assertFalse(payload["retryable"])

    def test_the_clinician_admits_the_patient_and_the_patient_gets_a_token(self):
        room = self.payload(self.open_room())
        room_id = room["room_id"]
        self.call("POST", f"/rooms/{room_id}/join", token=self.token_for(self.patient))

        response = self.call("POST", f"/rooms/{room_id}/admit",
                             token=self.token_for(self.practitioner),
                             body={"participant": self.patient.user_id})
        self.assertEqual(response.status, 200)

        response = self.call("GET", f"/rooms/{room_id}/token", token=self.token_for(self.patient))
        self.assertEqual(response.status, 200)
        payload = self.payload(response)
        self.assertTrue(payload["token"])
        self.assertEqual(payload["room_id"], room_id)

    def test_a_patient_who_is_not_admitted_gets_no_token(self):
        room = self.payload(self.open_room())
        response = self.call("GET", f"/rooms/{room['room_id']}/token",
                             token=self.token_for(self.patient))
        self.assertEqual(response.status, 409)
        self.assertEqual(self.payload(response)["error"], "not_admitted")
        self.assertTrue(self.payload(response)["retryable"])

    def test_a_patient_cannot_admit_themselves(self):
        room = self.payload(self.open_room())
        room_id = room["room_id"]
        self.call("POST", f"/rooms/{room_id}/join", token=self.token_for(self.patient))
        response = self.call("POST", f"/rooms/{room_id}/admit",
                             token=self.token_for(self.patient),
                             body={"participant": self.patient.user_id})
        self.assertEqual(response.status, 403)

    def test_the_room_state_is_visible_to_the_participants(self):
        room = self.payload(self.open_room())
        room_id = room["room_id"]
        self.call("POST", f"/rooms/{room_id}/join", token=self.token_for(self.patient))
        response = self.call("GET", f"/rooms/{room_id}", token=self.token_for(self.practitioner))
        self.assertEqual(response.status, 200)
        payload = self.payload(response)
        self.assertEqual(payload["waiting"], [self.patient.user_id])

    def test_an_unknown_room_is_not_found(self):
        response = self.call("GET", "/rooms/room-nobody", token=self.token_for(self.patient))
        self.assertEqual(response.status, 404)
        self.assertEqual(self.payload(response)["error"], "not_found")

    def test_an_unsupported_method_is_reported(self):
        response = self.call("DELETE", "/rooms", token=self.token_for(self.practitioner))
        self.assertEqual(response.status, 405)

    def test_a_response_is_not_cacheable(self):
        response = self.open_room()
        self.assertIn("no-store", response.headers["Cache-Control"])


class VideoOverHttpTest(VideoApiTestCase):
    """The same, over a real socket, with both applications on one server."""

    def setUp(self):
        super().setUp()
        self.server = make_server({"/video": self.application}, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, token=None, body=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, data=data, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_opening_and_joining_over_http(self):
        status, room = self.request(
            "POST", "/video/rooms", self.token_for(self.practitioner),
            {"appointment": self.appointment.appointment_id})
        self.assertEqual(status, 201)

        status, result = self.request("POST", f"/video/rooms/{room['room_id']}/join",
                                      self.token_for(self.patient))
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "waiting")

    def test_an_unauthenticated_join_over_http(self):
        status, payload = self.request("POST", "/video/rooms/room-nobody/join")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "login")


if __name__ == "__main__":
    unittest.main()
