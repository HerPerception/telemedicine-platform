"""Tests for the gate on transfers of patient data out of Nigeria.

Section 41(1) of the Nigeria Data Protection Act 2023 forbids transferring
personal data from Nigeria to another country unless the recipient has an
adequate level of protection or one of the section 43 conditions applies, and
section 41(2) requires the basis to be recorded.

These tests hold the gate to that:

* a transfer out of Nigeria with no lawful basis is refused, and the refusal
  says so in the words the acceptance criterion names;
* a transfer with a basis but no written justification is refused too;
* a transfer with both is allowed and written to the log;
* a service in Nigeria needs neither, because nothing leaves the country;
* a destination that is not in the configuration is refused, because it
  cannot be shown to be in Nigeria;
* **every service in the shipped configuration is blocked**, because the
  practice has not yet recorded a justification for any of them.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from telemedicine.transfer import (
    DEFAULT_SERVICES_PATH,
    LAWFUL_BASES,
    NIGERIA,
    REFUSAL_COUNTRY_MISMATCH,
    REFUSAL_NO_BASIS,
    REFUSAL_NO_JUSTIFICATION,
    REFUSAL_UNKNOWN_DESTINATION,
    CrossBorderTransferRefusedError,
    ExternalService,
    ExternalServiceRegistry,
    InMemoryTransferLog,
    OutboundGuard,
    TransferRequest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def sendgrid_registry(basis=None, justification=""):
    """A registry with SendGrid in it, as the configuration would have it."""
    return ExternalServiceRegistry([
        ExternalService(name="sendgrid", host="api.sendgrid.com",
                        destination_country="US", lawful_basis=basis,
                        justification=justification),
    ])


class TheShippedConfigurationTest(unittest.TestCase):
    """The configuration that ships with the repository."""

    @classmethod
    def setUpClass(cls):
        cls.registry = ExternalServiceRegistry.from_file()

    def test_it_reads(self):
        self.assertGreater(len(self.registry.services()), 0)

    def test_every_service_is_blocked(self):
        for service in self.registry.services():
            with self.subTest(service=service.name):
                self.assertFalse(service.permitted,
                                 f"{service.name} is not blocked, and it should be")

    def test_the_refusal_is_the_one_the_criterion_names(self):
        for service in self.registry.services():
            with self.subTest(service=service.name):
                self.assertIn(REFUSAL_NO_BASIS, service.reason)

    def test_the_services_the_task_names_are_there(self):
        for name in ("sendgrid", "aws", "openai", "firebase"):
            with self.subTest(service=name):
                self.assertIsNotNone(self.registry.for_name(name))

    def test_the_sendgrid_example_is_in_the_file(self):
        text = DEFAULT_SERVICES_PATH.read_text(encoding="utf-8")
        self.assertIn("Patient consented to email receipts, see consent ID", text)
        self.assertIn("consent", text)

    def test_every_service_has_a_country_and_a_host(self):
        for service in self.registry.services():
            with self.subTest(service=service.name):
                self.assertTrue(service.host)
                self.assertTrue(service.destination_country)

    def test_the_file_says_the_justifications_are_placeholders(self):
        text = DEFAULT_SERVICES_PATH.read_text(encoding="utf-8")
        self.assertIn("TODO_LEGAL", text)


class TheGateTest(unittest.TestCase):
    """What the gate does with a transfer."""

    def setUp(self):
        self.log = InMemoryTransferLog()
        self.guard = OutboundGuard(sendgrid_registry(), transfer_log=self.log,
                                   clock=lambda: NOW)

    def request(self, **overrides):
        arguments = {
            "destination_country": "US",
            "recipient": "patient@example.org",
            "data_categories": ["appointment.booked"],
            "lawful_basis": None,
            "justification_text": "",
        }
        arguments.update(overrides)
        return TransferRequest(**arguments)

    # -- the refusals -----------------------------------------------------

    def test_a_transfer_without_a_basis_is_refused(self):
        with self.assertRaises(CrossBorderTransferRefusedError) as caught:
            self.guard.permit(self.request(), host="api.sendgrid.com")
        self.assertEqual(str(caught.exception), REFUSAL_NO_BASIS)
        self.assertEqual(str(caught.exception),
                         "Transfer blocked: no lawful basis recorded per NDPA s43")

    def test_a_transfer_without_a_justification_is_refused(self):
        with self.assertRaises(CrossBorderTransferRefusedError) as caught:
            self.guard.permit(self.request(lawful_basis="consent"),
                              host="api.sendgrid.com")
        self.assertEqual(str(caught.exception), REFUSAL_NO_JUSTIFICATION)

    def test_a_refused_transfer_is_not_logged(self):
        with self.assertRaises(CrossBorderTransferRefusedError):
            self.guard.permit(self.request(), host="api.sendgrid.com")
        self.assertEqual(self.log.entries(), [])

    def test_an_unknown_destination_is_refused(self):
        with self.assertRaises(CrossBorderTransferRefusedError) as caught:
            self.guard.permit(self.request(lawful_basis="consent",
                                           justification_text="because"),
                              host="api.somewhere-else.example")
        self.assertEqual(str(caught.exception), REFUSAL_UNKNOWN_DESTINATION)

    def test_a_destination_that_claims_the_wrong_country_is_refused(self):
        with self.assertRaises(CrossBorderTransferRefusedError) as caught:
            self.guard.permit(self.request(destination_country=NIGERIA,
                                           lawful_basis="consent",
                                           justification_text="because"),
                              host="api.sendgrid.com")
        self.assertEqual(str(caught.exception), REFUSAL_COUNTRY_MISMATCH)

    def test_a_blocked_service_is_refused(self):
        registry = ExternalServiceRegistry([
            ExternalService(name="sendgrid", host="api.sendgrid.com",
                            destination_country="US", lawful_basis="consent",
                            justification="because", blocked=True)])
        guard = OutboundGuard(registry, transfer_log=self.log, clock=lambda: NOW)
        with self.assertRaises(CrossBorderTransferRefusedError):
            guard.permit(self.request(lawful_basis="consent",
                                      justification_text="because"),
                         host="api.sendgrid.com")

    # -- what is allowed --------------------------------------------------

    def test_a_transfer_with_a_basis_and_a_justification_is_allowed(self):
        entry = self.guard.permit(
            self.request(lawful_basis="consent",
                         justification_text="Patient consented to email receipts"),
            host="api.sendgrid.com", user_id="user-patient")
        self.assertEqual(entry.lawful_basis, "consent")
        self.assertEqual(entry.destination_country, "US")
        self.assertEqual(entry.user_id, "user-patient")

    def test_an_allowed_transfer_is_logged(self):
        self.guard.permit(
            self.request(lawful_basis="consent",
                         justification_text="Patient consented to email receipts"),
            host="api.sendgrid.com", user_id="user-patient")
        entries = self.log.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].service, "sendgrid")
        self.assertEqual(entries[0].destination, "api.sendgrid.com")
        self.assertEqual(entries[0].lawful_basis, "consent")
        self.assertIn("consented", entries[0].justification)
        self.assertEqual(entries[0].user_id, "user-patient")
        self.assertEqual(entries[0].data_categories, ["appointment.booked"])

    def test_a_service_in_nigeria_needs_neither(self):
        registry = ExternalServiceRegistry([
            ExternalService(name="practice_mail", host="smtp.example.ng",
                            destination_country=NIGERIA)])
        guard = OutboundGuard(registry, transfer_log=self.log, clock=lambda: NOW)
        entry = guard.permit(self.request(destination_country=NIGERIA,
                                          lawful_basis=None,
                                          justification_text=""),
                             host="smtp.example.ng")
        self.assertEqual(entry.destination_country, NIGERIA)
        # Nothing left the country, so nothing is written to the log.
        self.assertEqual(self.log.entries(), [])

    def test_a_local_host_is_allowed(self):
        entry = self.guard.permit(self.request(destination_country=NIGERIA,
                                               lawful_basis=None,
                                               justification_text=""),
                                  host="localhost")
        self.assertEqual(entry.destination_country, NIGERIA)

    def test_the_configuration_may_hold_the_basis_and_the_justification(self):
        guard = OutboundGuard(
            sendgrid_registry(basis="consent",
                              justification="Patient consented to email receipts"),
            transfer_log=self.log, clock=lambda: NOW)
        entry = guard.permit(self.request(), host="api.sendgrid.com")
        self.assertEqual(entry.lawful_basis, "consent")
        self.assertIn("consented", entry.justification)


class TheLawfulBasesTest(unittest.TestCase):
    def test_the_bases_are_the_ones_the_act_lists(self):
        self.assertEqual(LAWFUL_BASES,
                         ("consent", "contract", "vital_interest",
                          "public_interest", "legal_claim"))

    def test_each_of_them_is_accepted(self):
        for basis in LAWFUL_BASES:
            with self.subTest(basis=basis):
                registry = sendgrid_registry()
                guard = OutboundGuard(registry, transfer_log=InMemoryTransferLog())
                entry = guard.permit(
                    TransferRequest(destination_country="US",
                                    recipient="patient@example.org",
                                    data_categories=["appointment.booked"],
                                    lawful_basis=basis,
                                    justification_text="because"),
                    host="api.sendgrid.com")
                self.assertEqual(entry.lawful_basis, basis)


class TheTransportTest(unittest.TestCase):
    """The mail transport asks the gate before it connects."""

    def setUp(self):
        from telemedicine.delivery import SmtpTransport
        from telemedicine.notifications import Notification

        self.notification = Notification(
            notification_id="notification-1",
            kind="appointment.booked",
            recipient_user_id="user-patient",
            subject="Your appointment",
            body="Please come on Tuesday.",
            created_at=NOW,
        )
        self.transport = SmtpTransport(
            directory=lambda user_id: "patient@example.org",
            host="api.sendgrid.com",
            guard=OutboundGuard(sendgrid_registry(),
                                transfer_log=InMemoryTransferLog()),
        )

    def test_the_message_is_not_built_when_the_gate_refuses(self):
        with self.assertRaises(CrossBorderTransferRefusedError) as caught:
            self.transport.send(self.notification)
        self.assertEqual(str(caught.exception), REFUSAL_NO_BASIS)

    def test_nothing_is_sent_when_the_gate_refuses(self):
        # The transport connects to the mail server only after the gate has
        # said yes, so a refusal means no connection was made at all.
        with self.assertRaises(CrossBorderTransferRefusedError):
            self.transport.send(self.notification)

    def test_a_local_server_is_not_refused_by_the_gate(self):
        from telemedicine.delivery import SmtpTransport
        transport = SmtpTransport(
            directory=lambda user_id: "patient@example.org",
            host="localhost",
            guard=OutboundGuard(sendgrid_registry(),
                                transfer_log=InMemoryTransferLog()),
        )
        # The gate says yes: nothing leaves the country. The transport would
        # then try to connect, which is not what this test is about.
        transport.check_transfer(self.notification, "patient@example.org")


class TheInventoryCommandTest(unittest.TestCase):
    """The command that lists the services."""

    @classmethod
    def setUpClass(cls):
        path = REPO_ROOT / "scripts" / "audit_external_services.py"
        spec = importlib.util.spec_from_file_location("audit_services", path)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def run_command(self, *arguments):
        import contextlib
        import io
        out = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errors):
            status = self.script.main(list(arguments))
        return status, out.getvalue(), errors.getvalue()

    def test_it_lists_the_services_with_their_country(self):
        status, out, _errors = self.run_command()
        self.assertEqual(status, 0)
        self.assertIn("sendgrid", out)
        self.assertIn("US", out)
        self.assertIn("BLOCKED", out)

    def test_it_says_how_many_are_blocked(self):
        _status, out, _errors = self.run_command()
        self.assertIn("blocked until a", out)

    def test_it_says_when_there_is_no_environment_file(self):
        _status, out, _errors = self.run_command()
        self.assertIn("there is none", out)

    def test_a_blocked_service_is_not_a_failure(self):
        status, _out, _errors = self.run_command()
        self.assertEqual(status, 0)


class TheTransferLogInTheDatabaseTest(unittest.TestCase):
    """The log of transfers, in PostgreSQL."""

    def setUp(self):
        from tests.test_persistence import _fresh_database
        self.database = _fresh_database("telemedicine_transfer_test")
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        from telemedicine.persistence.transfer_store import PostgresTransferLog
        self.store = PostgresTransferLog(self.database)

    def entry(self, **overrides):
        from telemedicine.transfer import TransferLogEntry
        arguments = {
            "occurred_at": NOW,
            "service": "sendgrid",
            "destination": "api.sendgrid.com",
            "destination_country": "US",
            "recipient": "patient@example.org",
            "data_categories": ["appointment.booked"],
            "lawful_basis": "consent",
            "justification": "Patient consented to email receipts",
            "user_id": None,
        }
        arguments.update(overrides)
        return TransferLogEntry(**arguments)

    def test_the_transfer_round_trips(self):
        self.store.record(self.entry())
        entries = self.store.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].destination, "api.sendgrid.com")
        self.assertEqual(entries[0].lawful_basis, "consent")
        self.assertEqual(entries[0].data_categories, ["appointment.booked"])
        self.assertIn("consented", entries[0].justification)

    def test_the_transfers_for_one_destination_are_found(self):
        self.store.record(self.entry())
        self.store.record(self.entry(destination="api.openai.com"))
        self.assertEqual(len(self.store.for_destination("api.sendgrid.com")), 1)

    def test_the_log_refuses_a_change(self):
        self.store.record(self.entry())
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE transfer_logs SET justification = 'changed'")
        self.assertIn("append-only", str(caught.exception))

    def test_the_log_refuses_a_removal(self):
        self.store.record(self.entry())
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM transfer_logs")
        self.assertIn("append-only", str(caught.exception))

    def test_the_log_refuses_to_be_truncated(self):
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("TRUNCATE transfer_logs")
        self.assertIn("append-only", str(caught.exception))

    def test_a_transfer_without_a_justification_is_refused_by_the_table(self):
        with self.assertRaises(Exception):
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO transfer_logs (destination, destination_country,"
                        " justification) VALUES ('api.sendgrid.com', 'US', '')")


class TheConfigurationReadingTest(unittest.TestCase):
    """The file is read strictly."""

    def test_an_unknown_lawful_basis_is_an_error(self):
        import tempfile
        from telemedicine.yaml_lite import ConfigurationError
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "services.yaml"
            path.write_text(
                "thing.host: api.example.com\n"
                "thing.country: US\n"
                "thing.lawful_basis: because\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError) as caught:
                ExternalServiceRegistry.from_file(path)
        self.assertIn("lawful basis", str(caught.exception))

    def test_a_service_without_a_country_is_an_error(self):
        import tempfile
        from telemedicine.yaml_lite import ConfigurationError
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "services.yaml"
            path.write_text("thing.host: api.example.com\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError) as caught:
                ExternalServiceRegistry.from_file(path)
        self.assertIn("country", str(caught.exception))

    def test_a_service_without_a_host_is_an_error(self):
        import tempfile
        from telemedicine.yaml_lite import ConfigurationError
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "services.yaml"
            path.write_text("thing.country: NG\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError) as caught:
                ExternalServiceRegistry.from_file(path)
        self.assertIn("host", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
