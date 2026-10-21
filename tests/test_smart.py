"""Tests for SMART on FHIR.

**The most important thing these tests say is that nothing changes while
SMART is off.** The flag is off by default, the endpoints are not
registered, and the ordinary sign-in works exactly as it did — that is the
MVP, and it is what a practice with no hospital connection needs.

With the flag on, the tests check the discovery document, the redirect to
the record, and the whole round trip: the code is exchanged at the record's
own token endpoint, the record is asked who the clinician is, and the
clinician is signed in.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telemedicine.audit import AuditLog
from telemedicine.auth import AuthService
from telemedicine.models import Role
from telemedicine.smart import (
    CAPABILITIES,
    SmartError,
    SmartNotConfigured,
    code_challenge,
    load_configuration,
    new_verifier,
    sign_state,
    start_flow,
    verify_state,
)
from telemedicine.smart_api import SmartApplication


class TheFlagTest(unittest.TestCase):
    """With the flag off, nothing is different."""

    def setUp(self):
        from telemedicine.application import build_application
        from telemedicine.config import Settings
        self.application = build_application(Settings())

    def test_the_flag_is_off_by_default(self):
        from telemedicine.config import Settings
        self.assertFalse(Settings().smart_fhir_enabled)

    def test_the_endpoints_are_not_registered(self):
        self.assertEqual(set(self.application.http.applications), {"/fhir", "/video"})

    def test_the_discovery_document_is_not_there(self):
        response = self.application.http.handle("GET", "/.well-known/smart-configuration")
        self.assertEqual(response.status, 404)

    def test_the_ordinary_sign_in_still_works(self):
        response = self.application.http.handle(
            "POST", "/fhir/session", {}, {},
            json.dumps({"email": "ada@example.org", "password": "a-long-passphrase"}
                       ).encode("utf-8"))
        # There is no such account in this application, so the sign-in is
        # refused — but it is refused as a sign-in, not as a missing
        # endpoint. The point is that the route is there.
        self.assertEqual(response.status, 401)


class TheConfigurationTest(unittest.TestCase):
    """The client registration."""

    def setUp(self):
        self.configuration = load_configuration()

    def test_it_is_off_by_default(self):
        self.assertFalse(self.configuration.enabled)

    def test_the_scopes_are_the_ones_the_task_asked_for(self):
        self.assertIn("patient/*.read", self.configuration.scopes)
        self.assertIn("user/MedicationRequest.write", self.configuration.scopes)

    def test_the_capabilities_are_the_ones_the_task_asked_for(self):
        self.assertEqual(CAPABILITIES, ("launch-ehr", "client-public"))

    def test_an_unconfigured_client_is_not_configured(self):
        self.assertFalse(self.configuration.configured)


class TheStateTest(unittest.TestCase):
    """The state carries the PKCE verifier, and it is signed."""

    SECRET = "a-state-secret"

    def test_a_state_round_trips(self):
        state = sign_state({"code_verifier": "the-verifier"}, self.SECRET)
        payload = verify_state(state, self.SECRET)
        self.assertEqual(payload["code_verifier"], "the-verifier")

    def test_a_state_that_was_changed_is_refused(self):
        import base64
        import json
        state = sign_state({"code_verifier": "the-verifier"}, self.SECRET)
        encoded, _, signature = state.partition(".")
        payload = json.loads(base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4)).decode("utf-8"))
        payload["code_verifier"] = "another-verifier"
        changed = base64.urlsafe_b64encode(json.dumps(
            payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        with self.assertRaises(SmartError):
            verify_state(f"{changed}.{signature}", self.SECRET)

    def test_a_state_signed_with_another_secret_is_refused(self):
        state = sign_state({"code_verifier": "the-verifier"}, self.SECRET)
        with self.assertRaises(SmartError):
            verify_state(state, "another-secret")

    def test_an_expired_state_is_refused(self):
        state = sign_state({"code_verifier": "v"}, self.SECRET, now=1000)
        with self.assertRaises(SmartError):
            verify_state(state, self.SECRET, now=1000 + 601)

    def test_the_challenge_is_the_hash_of_the_verifier(self):
        import base64
        import hashlib
        verifier = new_verifier()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        self.assertEqual(code_challenge(verifier), expected)

    def test_two_verifiers_are_different(self):
        self.assertNotEqual(new_verifier(), new_verifier())


class TheRecordStub(BaseHTTPRequestHandler):
    """A stand-in for a hospital's record."""

    token_calls = []
    userinfo_calls = []

    def do_POST(self):  # noqa: N802 - the name is fixed by the base class
        length = int(self.headers.get("Content-Length") or 0)
        body = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        TheRecordStub.token_calls.append(body)
        payload = json.dumps({"access_token": "an-ehr-token",
                              "token_type": "Bearer"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        TheRecordStub.userinfo_calls.append(self.path)
        payload = json.dumps({"email": "clinician@example.ng"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):  # noqa: A002
        """Keep the console quiet."""


class TheFlowTest(unittest.TestCase):
    """The whole round trip, against a stand-in for the record."""

    def setUp(self):
        TheRecordStub.token_calls = []
        TheRecordStub.userinfo_calls = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TheRecordStub)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        from telemedicine.smart import SmartConfiguration
        self.configuration = SmartConfiguration(
            enabled=True,
            authorization_endpoint=f"http://127.0.0.1:{self.port}/auth",
            token_endpoint=f"http://127.0.0.1:{self.port}/token",
            userinfo_endpoint=f"http://127.0.0.1:{self.port}/userinfo",
            issuer=f"http://127.0.0.1:{self.port}",
            client_id="the-client-id",
            redirect_uri="http://app.example.ng/smart/callback",
            scopes=("openid", "profile", "launch/patient", "patient/*.read",
                    "user/MedicationRequest.write"),
            identities={"clinician@example.ng": ""},
        )
        self.audit = AuditLog()
        self.auth = AuthService(audit=self.audit, password_iterations=1000)
        self.account = self.auth.register("clinician@example.ng", "a-long-passphrase",
                                           Role.PRACTITIONER, record_id="practitioner-1")
        self.configuration = SmartConfiguration(
            **{**self.configuration.__dict__,
               "identities": {"clinician@example.ng": self.account.user_id}})
        self.application = SmartApplication(self.configuration, self.auth,
                                            state_secret="a-state-secret")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, query=None):
        return self.application.handle(method, path, query or {}, {}, b"")

    # -- the discovery document -------------------------------------------

    def test_the_discovery_document_is_json(self):
        response = self.request("GET", "/.well-known/smart-configuration")
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["capabilities"], ["launch-ehr", "client-public"])
        self.assertIn("authorization_endpoint", payload)
        self.assertIn("token_endpoint", payload)

    def test_the_discovery_document_names_the_record(self):
        response = self.request("GET", "/.well-known/smart-configuration")
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["authorization_endpoint"].endswith("/auth"))
        self.assertTrue(payload["token_endpoint"].endswith("/token"))

    # -- the redirect ------------------------------------------------------

    def test_the_authorize_endpoint_redirects_to_the_record(self):
        response = self.request("GET", "/smart/authorize")
        self.assertEqual(response.status, 302)
        location = response.headers["Location"]
        self.assertIn("client_id=the-client-id", location)
        self.assertIn("response_type=code", location)
        self.assertIn("code_challenge_method=S256", location)
        self.assertIn("patient%2F%2A.read", location)

    # -- the round trip ----------------------------------------------------

    def test_the_callback_signs_the_clinician_in(self):
        # The browser goes out with a state, and comes back with a code.
        _state, url = start_flow(self.configuration, "a-state-secret")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        response = self.request("GET", "/smart/callback",
                                {"code": ["the-code"], "state": [state]})
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["token"])
        self.assertEqual(payload["user_id"], self.account.user_id)
        self.assertEqual(payload["role"], "practitioner")

    def test_the_code_is_exchanged_at_the_record(self):
        _state, url = start_flow(self.configuration, "a-state-secret")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        self.request("GET", "/smart/callback",
                     {"code": ["the-code"], "state": [state]})
        self.assertEqual(len(TheRecordStub.token_calls), 1)
        sent = TheRecordStub.token_calls[0]
        self.assertEqual(sent["code"], ["the-code"])
        self.assertEqual(sent["grant_type"], ["authorization_code"])
        self.assertTrue(sent["code_verifier"][0])

    def test_the_identity_comes_from_the_record(self):
        _state, url = start_flow(self.configuration, "a-state-secret")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        self.request("GET", "/smart/callback",
                     {"code": ["the-code"], "state": [state]})
        self.assertTrue(TheRecordStub.userinfo_calls)

    def test_a_state_that_was_changed_is_refused(self):
        _state, url = start_flow(self.configuration, "a-state-secret")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        response = self.request("GET", "/smart/callback",
                                {"code": ["the-code"], "state": [state[:-2] + "xy"]})
        self.assertEqual(response.status, 400)

    def test_a_clinician_the_practice_does_not_know_is_refused(self):
        from telemedicine.smart import SmartConfiguration
        configuration = SmartConfiguration(
            **{**self.configuration.__dict__, "identities": {}})
        application = SmartApplication(configuration, self.auth,
                                       state_secret="a-state-secret")
        _state, url = start_flow(configuration, "a-state-secret")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        response = application.handle("GET", "/smart/callback",
                                      {"code": ["the-code"], "state": [state]},
                                      {}, b"")
        self.assertEqual(response.status, 400)
        self.assertIn("clinician@example.ng",
                      json.loads(response.body.decode("utf-8"))["message"])

    def test_a_callback_without_a_code_is_refused(self):
        response = self.request("GET", "/smart/callback", {"state": ["x"]})
        self.assertEqual(response.status, 400)

    def test_an_unknown_path_is_not_found(self):
        self.assertEqual(self.request("GET", "/something-else").status, 404)


class TheApplicationWiringTest(unittest.TestCase):
    """The application mounts the SMART endpoints only when the flag is on."""

    def test_with_the_flag_on_the_endpoints_are_there(self):
        import tempfile
        from pathlib import Path
        from telemedicine.application import build_application
        from telemedicine.config import Settings
        with tempfile.TemporaryDirectory() as directory:
            registration = Path(directory) / "smart_clients.yaml"
            registration.write_text(
                "smart.enabled: true\n"
                "smart.authorization_endpoint: https://ehr.example.ng/auth\n"
                "smart.token_endpoint: https://ehr.example.ng/token\n"
                "smart.userinfo_endpoint: https://ehr.example.ng/userinfo\n"
                "smart.issuer: https://ehr.example.ng\n"
                "smart.client_id: the-client-id\n"
                "smart.redirect_uri: https://app.example.ng/smart/callback\n"
                "smart.scopes: openid patient/*.read\n", encoding="utf-8")
            application = build_application(Settings(
                smart_fhir_enabled=True, smart_state_secret="a-secret",
                smart_clients=str(registration)))
        self.assertIn("", application.http.applications)
        response = application.http.handle("GET", "/.well-known/smart-configuration")
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["capabilities"], ["launch-ehr", "client-public"])

    def test_with_the_flag_on_and_no_registration_the_application_says_so(self):
        from telemedicine.application import build_application
        from telemedicine.config import Settings
        with self.assertRaises(RuntimeError) as caught:
            build_application(Settings(smart_fhir_enabled=True,
                                        smart_state_secret="a-secret"))
        self.assertIn("client registration", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
