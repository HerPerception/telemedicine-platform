"""Tests for signing in and out, and for the lockout that counts addresses.

The session endpoints are the difference between an API a client can use
and one it cannot: without them there is no way to get a token over HTTP.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone

from telemedicine.audit import AuditLog
from telemedicine.auth import (
    ACCOUNT_THRESHOLD,
    SOURCE_THRESHOLD,
    AuthService,
)
from telemedicine.models import Role

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        from datetime import timedelta
        self.now = self.now + timedelta(**kwargs)
        return self.now


class SessionEndpointTest(unittest.TestCase):
    """Signing in and out, in process."""

    def setUp(self):
        self.clock = FakeClock()
        self.audit = AuditLog(clock=self.clock)
        self.auth = AuthService(audit=self.audit, password_iterations=1000, clock=self.clock)
        self.account = self.auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                          record_id="patient-1")
        from telemedicine.fhir.repository import FhirRepository
        from telemedicine.fhir.server import FhirApplication
        from telemedicine.records import RecordsService

        self.records = RecordsService(audit=self.audit)
        self.application = FhirApplication(
            FhirRepository(self.records, None, None), self.auth)

    def post(self, path, body, headers=None):
        return self.application.handle(
            "POST", path, {}, headers or {}, json.dumps(body).encode("utf-8"))

    def delete(self, path, headers=None):
        return self.application.handle("DELETE", path, {}, headers or {}, b"")

    def test_signing_in_returns_a_token(self):
        response = self.post("/fhir/session", {"email": "ada@example.org",
                                                "password": "a-long-passphrase"})
        self.assertEqual(response.status, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["token"])
        self.assertEqual(payload["user_id"], self.account.user_id)
        self.assertEqual(payload["role"], "patient")
        self.assertIn("expires_at", payload)

    def test_the_token_works(self):
        response = self.post("/fhir/session", {"email": "ada@example.org",
                                                "password": "a-long-passphrase"})
        token = json.loads(response.body.decode("utf-8"))["token"]
        accepted = self.auth.authenticate_session(token)
        self.assertEqual(accepted.user_id, self.account.user_id)

    def test_a_wrong_password_is_refused(self):
        response = self.post("/fhir/session", {"email": "ada@example.org",
                                                "password": "not-the-passphrase"})
        self.assertEqual(response.status, 401)
        self.assertEqual(json.loads(response.body.decode("utf-8"))["issue"][0]["code"], "login")

    def test_an_unknown_account_is_refused_the_same_way(self):
        unknown = self.post("/fhir/session", {"email": "nobody@example.org",
                                              "password": "a-long-passphrase"})
        wrong = self.post("/fhir/session", {"email": "ada@example.org",
                                            "password": "not-the-passphrase"})
        self.assertEqual(unknown.status, wrong.status)
        self.assertEqual(unknown.body, wrong.body)

    def test_a_body_without_a_password_is_refused(self):
        response = self.post("/fhir/session", {"email": "ada@example.org"})
        self.assertEqual(response.status, 400)

    def test_signing_out_ends_the_session(self):
        response = self.post("/fhir/session", {"email": "ada@example.org",
                                                "password": "a-long-passphrase"})
        token = json.loads(response.body.decode("utf-8"))["token"]
        response = self.delete("/fhir/session", {"authorization": f"Bearer {token}"})
        self.assertEqual(response.status, 204)
        with self.assertRaises(Exception):
            self.auth.authenticate_session(token)

    def test_signing_out_without_a_token_is_refused(self):
        response = self.delete("/fhir/session")
        self.assertEqual(response.status, 401)

    def test_the_sign_in_is_audited(self):
        self.post("/fhir/session", {"email": "ada@example.org", "password": "a-long-passphrase"})
        logins = [entry for entry in self.audit.entries if entry.action == "auth.login"]
        self.assertTrue(logins)
        self.assertEqual(logins[0].outcome, "success")


class SourceLockoutTest(unittest.TestCase):
    """The lockout counts the address as well as the account."""

    def setUp(self):
        self.clock = FakeClock()
        self.audit = AuditLog(clock=self.clock)
        self.auth = AuthService(audit=self.audit, password_iterations=1000, clock=self.clock)
        self.account = self.auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                          record_id="patient-1")

    def fail_from(self, source, times=1):
        from telemedicine.errors import AuthenticationError
        for _ in range(times):
            with self.assertRaises(AuthenticationError):
                self.auth.authenticate("ada@example.org", "not-the-passphrase", source=source)

    def test_one_address_is_blocked_after_enough_failures(self):
        self.fail_from("203.0.113.7", times=SOURCE_THRESHOLD)
        # The address is now blocked, and the right password does not help.
        from telemedicine.errors import AuthenticationError
        with self.assertRaises(AuthenticationError):
            self.auth.authenticate("ada@example.org", "a-long-passphrase", source="203.0.113.7")

    def test_one_address_cannot_lock_the_account(self):
        # The account counter grows once per address, so one address guessing
        # for ever cannot reach the account threshold.
        self.fail_from("203.0.113.7", times=SOURCE_THRESHOLD * 3)
        from telemedicine.errors import AuthenticationError
        with self.assertRaises(AuthenticationError):
            self.auth.authenticate("ada@example.org", "a-long-passphrase", source="203.0.113.7")
        # From anywhere else, the account still works.
        account = self.auth.authenticate("ada@example.org", "a-long-passphrase",
                                         source="198.51.100.4")
        self.assertEqual(account.user_id, self.account.user_id)

    def test_failures_spread_over_many_addresses_lock_the_account(self):
        for index in range(ACCOUNT_THRESHOLD):
            self.fail_from(f"203.0.113.{index}", times=1)
        from telemedicine.errors import AuthenticationError
        with self.assertRaises(AuthenticationError):
            self.auth.authenticate("ada@example.org", "a-long-passphrase",
                                   source="198.51.100.4")

    def test_a_successful_login_clears_the_counters(self):
        self.fail_from("203.0.113.7", times=2)
        self.auth.authenticate("ada@example.org", "a-long-passphrase", source="203.0.113.7")
        # The counters are clear, so the same address may try again.
        from telemedicine.errors import AuthenticationError
        with self.assertRaises(AuthenticationError):
            self.auth.authenticate("ada@example.org", "not-the-passphrase", source="203.0.113.7")
        self.assertEqual(self.auth.lockout.attempts("account:ada@example.org"), 1)


class ForwardedAddressTest(unittest.TestCase):
    """The address a proxy reports is only believed when it is asked for."""

    def setUp(self):
        self.clock = FakeClock()
        self.audit = AuditLog(clock=self.clock)
        self.auth = AuthService(audit=self.audit, password_iterations=1000, clock=self.clock)
        self.auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                           record_id="patient-1")
        from telemedicine.session_api import SessionEndpoints

        self.trusting = SessionEndpoints(self.auth, trust_forwarded_for=True)
        self.not_trusting = SessionEndpoints(self.auth, trust_forwarded_for=False)

    def test_the_forwarded_address_is_used_when_it_is_trusted(self):
        headers = {"x-forwarded-for": "198.51.100.4, 10.0.0.1"}
        self.assertEqual(self.trusting.source(headers), "198.51.100.4")

    def test_the_forwarded_address_is_ignored_by_default(self):
        headers = {"x-forwarded-for": "198.51.100.4", "x-client-address": "203.0.113.7"}
        self.assertEqual(self.not_trusting.source(headers), "203.0.113.7")

    def test_without_a_proxy_the_socket_address_is_used(self):
        headers = {"x-client-address": "203.0.113.7"}
        self.assertEqual(self.trusting.source(headers), "203.0.113.7")


class SessionOverHttpTest(unittest.TestCase):
    """The same, over a real socket."""

    def setUp(self):
        import threading

        from telemedicine.booking import BookingService, SlotService
        from telemedicine.fhir.repository import FhirRepository
        from telemedicine.fhir.server import FhirApplication, make_server
        from telemedicine.prescriptions import PrescriptionService
        from telemedicine.records import RecordsService
        from telemedicine.video import VideoService
        from telemedicine.video_api import VideoApplication

        self.audit = AuditLog()
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit)
        self.booking = BookingService(self.slots, records=self.records, audit=self.audit)
        self.prescriptions = PrescriptionService(self.records, audit=self.audit)
        self.auth = AuthService(audit=self.audit, password_iterations=1000)
        self.auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                           record_id="patient-1")

        fhir = FhirApplication(
            FhirRepository(self.records, self.booking, self.prescriptions), self.auth)
        video = VideoApplication(VideoService(self.records, audit=self.audit), self.auth)

        from telemedicine.fhir.server import ApplicationRouter
        self.server = make_server(ApplicationRouter({"/fhir": fhir, "/video": video}),
                                 "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, token=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, data=data, timeout=15) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8") or "{}")

    def test_signing_in_over_http(self):
        status, payload = self.request("POST", "/fhir/session",
                                       {"email": "ada@example.org",
                                        "password": "a-long-passphrase"})
        self.assertEqual(status, 201)
        self.assertTrue(payload["token"])

    def test_the_video_surface_can_sign_in_too(self):
        status, payload = self.request("POST", "/video/session",
                                       {"email": "ada@example.org",
                                        "password": "a-long-passphrase"})
        self.assertEqual(status, 201)
        self.assertTrue(payload["token"])

    def test_a_wrong_password_over_http(self):
        status, payload = self.request("POST", "/fhir/session",
                                       {"email": "ada@example.org", "password": "wrong"})
        self.assertEqual(status, 401)
        self.assertEqual(payload["issue"][0]["code"], "login")

    def test_signing_out_over_http(self):
        _status, payload = self.request("POST", "/fhir/session",
                                        {"email": "ada@example.org",
                                         "password": "a-long-passphrase"})
        token = payload["token"]
        status, _body = self.request("DELETE", "/fhir/session", token=token)
        self.assertEqual(status, 204)
        # The token no longer opens anything.
        status, _body = self.request("GET", "/fhir/Patient/patient-1", token=token)
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
