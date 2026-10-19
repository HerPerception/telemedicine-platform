"""Tests for authentication: accounts, passwords and sessions.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog
from telemedicine.auth import (
    ACTION_ACCOUNT_CREATE,
    ACTION_LOGIN,
    ACTION_LOGOUT,
    AuthService,
    mask_email,
)
from telemedicine.errors import AuthenticationError, ValidationError
from telemedicine.models import Role
from telemedicine.security import hash_password, hash_token, verify_password

# The production default is 600,000 iterations, which is deliberately slow.
# The tests use a small count so the suite stays fast; the algorithm under
# test is the same.
TEST_ITERATIONS = 1000


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, start=None):
        self.now = start or datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)
        return self.now


def build_service(clock=None, session_ttl=timedelta(hours=8)):
    clock = clock or FakeClock()
    audit = AuditLog(clock=clock)
    service = AuthService(
        audit=audit,
        password_iterations=TEST_ITERATIONS,
        session_ttl=session_ttl,
        clock=clock,
    )
    return service, audit, clock


class PasswordHashingTest(unittest.TestCase):
    def test_hash_is_not_the_password(self):
        encoded = hash_password("correct horse battery staple", iterations=TEST_ITERATIONS)
        self.assertNotIn("correct horse battery staple", encoded)
        self.assertTrue(encoded.startswith("pbkdf2_sha256$"))

    def test_same_password_gets_a_different_hash_each_time(self):
        first = hash_password("correct horse battery staple", iterations=TEST_ITERATIONS)
        second = hash_password("correct horse battery staple", iterations=TEST_ITERATIONS)
        self.assertNotEqual(first, second, "each hash must use a fresh salt")

    def test_verify_accepts_the_right_password_and_rejects_others(self):
        encoded = hash_password("correct horse battery staple", iterations=TEST_ITERATIONS)
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))
        self.assertFalse(verify_password("", encoded))

    def test_verify_rejects_malformed_hashes(self):
        self.assertFalse(verify_password("x", "not-a-hash"))
        self.assertFalse(verify_password("x", "pbkdf2_sha256$abc$salt$hash"))
        self.assertFalse(verify_password("x", ""))

    def test_token_digest_is_stable_and_hides_the_token(self):
        token = "a-session-token-value"
        digest = hash_token(token)
        self.assertEqual(digest, hash_token(token))
        self.assertNotIn(token, digest)
        self.assertEqual(len(digest), 64)


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        self.service, self.audit, self.clock = build_service()

    def test_register_creates_an_account_for_each_role(self):
        patient = self.service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                        record_id="patient-1")
        practitioner = self.service.register("dr@example.org", "a-long-passphrase",
                                             Role.PRACTITIONER, record_id="practitioner-1")
        self.assertEqual(patient.role, Role.PATIENT)
        self.assertEqual(practitioner.role, Role.PRACTITIONER)
        self.assertEqual(patient.email, "ada@example.org")
        self.assertEqual(len(self.service.users), 2)

    def test_register_normalises_the_email(self):
        account = self.service.register("  Ada@Example.ORG ", "a-long-passphrase",
                                        Role.PATIENT, record_id="patient-1")
        self.assertEqual(account.email, "ada@example.org")

    def test_register_requires_a_record_id_for_a_patient(self):
        with self.assertRaises(ValueError):
            self.service.register("ada@example.org", "a-long-passphrase", Role.PATIENT)

    def test_register_rejects_a_weak_password(self):
        with self.assertRaises(ValidationError):
            self.service.register("ada@example.org", "short", Role.PATIENT, record_id="patient-1")

    def test_register_rejects_the_email_as_the_password(self):
        with self.assertRaises(ValidationError):
            self.service.register("ada@example.org", "ada@example.org", Role.PATIENT,
                                  record_id="patient-1")

    def test_register_rejects_a_duplicate_email(self):
        self.service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                               record_id="patient-1")
        with self.assertRaises(ValidationError):
            self.service.register("ada@example.org", "another-passphrase", Role.PATIENT,
                                  record_id="patient-2")

    def test_register_is_audited(self):
        self.service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                              record_id="patient-1")
        entries = self.audit.entries_for_outcome(OUTCOME_SUCCESS)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].action, ACTION_ACCOUNT_CREATE)


class AuthenticationTest(unittest.TestCase):
    def setUp(self):
        self.service, self.audit, self.clock = build_service()
        self.patient = self.service.register("ada@example.org", "a-long-passphrase",
                                              Role.PATIENT, record_id="patient-1")
        self.practitioner = self.service.register("dr@example.org", "a-long-passphrase",
                                                  Role.PRACTITIONER,
                                                  record_id="practitioner-1")

    def test_both_roles_authenticate(self):
        self.assertEqual(self.service.authenticate("ada@example.org", "a-long-passphrase").role,
                         Role.PATIENT)
        self.assertEqual(self.service.authenticate("dr@example.org", "a-long-passphrase").role,
                         Role.PRACTITIONER)

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(AuthenticationError):
            self.service.authenticate("ada@example.org", "not-the-passphrase")

    def test_unknown_account_is_rejected_with_the_same_message(self):
        with self.assertRaises(AuthenticationError) as unknown:
            self.service.authenticate("nobody@example.org", "a-long-passphrase")
        with self.assertRaises(AuthenticationError) as wrong:
            self.service.authenticate("ada@example.org", "not-the-passphrase")
        self.assertEqual(str(unknown.exception), str(wrong.exception))

    def test_malformed_email_is_rejected(self):
        with self.assertRaises(AuthenticationError):
            self.service.authenticate("not-an-email", "a-long-passphrase")

    def test_disabled_account_cannot_log_in(self):
        self.service.disable(self.patient)
        with self.assertRaises(AuthenticationError):
            self.service.authenticate("ada@example.org", "a-long-passphrase")

    def test_successful_login_is_audited(self):
        self.service.authenticate("ada@example.org", "a-long-passphrase")
        successes = [entry for entry in self.audit.entries
                     if entry.action == ACTION_LOGIN and entry.outcome == OUTCOME_SUCCESS]
        self.assertEqual(len(successes), 1)
        self.assertEqual(successes[0].actor_user_id, self.patient.user_id)

    def test_failed_login_is_audited_without_the_full_email(self):
        with self.assertRaises(AuthenticationError):
            self.service.authenticate("ada@example.org", "not-the-passphrase")
        failures = [entry for entry in self.audit.entries
                    if entry.action == ACTION_LOGIN and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(failures), 1)
        self.assertNotIn("ada@example.org", failures[0].detail)
        self.assertIn("a***@example.org", failures[0].detail)

    def test_mask_email(self):
        self.assertEqual(mask_email("ada@example.org"), "a***@example.org")
        self.assertEqual(mask_email("nonsense"), "unknown")

    def test_password_change_requires_the_current_password(self):
        with self.assertRaises(AuthenticationError):
            self.service.set_password(self.patient, "not-the-passphrase", "a-new-long-passphrase")
        updated = self.service.set_password(self.patient, "a-long-passphrase",
                                            "a-new-long-passphrase")
        self.assertTrue(verify_password("a-new-long-passphrase", updated.password_hash))
        self.assertEqual(self.service.authenticate("ada@example.org",
                                                    "a-new-long-passphrase").user_id,
                         self.patient.user_id)


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.service, self.audit, self.clock = build_service(
            session_ttl=timedelta(minutes=30))
        self.patient = self.service.register("ada@example.org", "a-long-passphrase",
                                              Role.PATIENT, record_id="patient-1")

    def test_create_session_returns_a_usable_token(self):
        token, session = self.service.create_session(self.patient)
        self.assertTrue(token)
        self.assertEqual(self.service.authenticate_session(token).user_id,
                         self.patient.user_id)
        self.assertEqual(session.user_id, self.patient.user_id)

    def test_the_raw_token_is_never_stored(self):
        token, session = self.service.create_session(self.patient)
        stored = self.service.sessions.get(token)
        self.assertEqual(stored.token_hash, hash_token(token))
        self.assertNotIn(token, stored.token_hash)

    def test_an_unknown_token_is_rejected(self):
        with self.assertRaises(AuthenticationError):
            self.service.authenticate_session("not-a-real-token")

    def test_an_expired_session_is_rejected(self):
        token, _ = self.service.create_session(self.patient)
        self.clock.advance(minutes=31)
        with self.assertRaises(AuthenticationError):
            self.service.authenticate_session(token)

    def test_a_session_is_valid_before_it_expires(self):
        token, _ = self.service.create_session(self.patient)
        self.clock.advance(minutes=29)
        self.assertEqual(self.service.authenticate_session(token).user_id, self.patient.user_id)

    def test_logout_revokes_the_session(self):
        token, _ = self.service.create_session(self.patient)
        self.service.revoke_session(token)
        with self.assertRaises(AuthenticationError):
            self.service.authenticate_session(token)

    def test_logout_is_audited(self):
        token, _ = self.service.create_session(self.patient)
        self.service.revoke_session(token)
        logouts = [entry for entry in self.audit.entries if entry.action == ACTION_LOGOUT]
        self.assertEqual(len(logouts), 1)
        self.assertEqual(logouts[0].outcome, OUTCOME_SUCCESS)

    def test_logout_of_an_unknown_token_is_not_an_error(self):
        self.service.revoke_session("not-a-real-token")

    def test_a_disabled_account_cannot_use_an_existing_session(self):
        token, _ = self.service.create_session(self.patient)
        self.service.disable(self.patient)
        with self.assertRaises(AuthenticationError):
            self.service.authenticate_session(token)

    def test_a_disabled_account_cannot_start_a_session(self):
        self.service.disable(self.patient)
        with self.assertRaises(AuthenticationError):
            self.service.create_session(self.patient)


if __name__ == "__main__":
    unittest.main()
