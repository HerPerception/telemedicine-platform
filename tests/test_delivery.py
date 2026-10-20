"""Tests for the delivery worker and the mail transport.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

from telemedicine.audit import AuditLog
from telemedicine.delivery import (
    DeliveryWorker,
    SmtpTransport,
    directory_from_users,
)
from telemedicine.models import Role
from telemedicine.notifications import (
    MAX_ATTEMPTS,
    InMemoryNotificationStore,
    NotificationService,
    RecordingTransport,
)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def account(user_id, email):
    from telemedicine.models import UserAccount
    return UserAccount(user_id=user_id, email=email, role=Role.PATIENT,
                       password_hash="pbkdf2_sha256$1000$abc$def", record_id="patient-1")


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.clock = _FakeClock()
        self.audit = AuditLog(clock=self.clock)
        self.store = InMemoryNotificationStore()
        self.transport = RecordingTransport()
        self.service = NotificationService(store=self.store, transport=self.transport,
                                          audit=self.audit, clock=self.clock)
        self.worker = DeliveryWorker(self.service, interval=1,
                                     sleeper=lambda seconds: None)

    def queue(self, recipient="user-1"):
        return self.service.queue(kind="appointment.booked", recipient_user_id=recipient,
                                  subject="Your appointment is booked", body="When: ...")

    def test_the_worker_sends_what_is_queued(self):
        self.queue()
        report = self.worker.run_once()
        self.assertEqual(report.sent, 1)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.store.pending(), [])

    def test_the_worker_keeps_going(self):
        self.queue()
        self.queue()
        reports = self.worker.run_forever(max_iterations=3)
        self.assertEqual(len(reports), 3)
        # The queue is empty after the first pass, and the later passes do
        # nothing.
        self.assertEqual(reports[0].sent, 2)
        self.assertEqual(reports[1].sent, 0)
        self.assertEqual(reports[2].sent, 0)

    def test_a_message_that_cannot_be_sent_is_not_lost(self):
        from telemedicine.notifications import NotificationService
        transport = RecordingTransport(fail_with="the mail server refused")
        service = NotificationService(store=InMemoryNotificationStore(),
                                     transport=transport, audit=self.audit,
                                     clock=self.clock)
        worker = DeliveryWorker(service, interval=1, sleeper=lambda seconds: None)
        service.queue(kind="appointment.booked", recipient_user_id="user-1",
                      subject="s", body="b")

        report = worker.run_once()
        self.assertEqual(report.failed, 1)
        self.assertEqual(report.sent, 0)
        # It is still queued, with the error recorded.
        pending = service.store.pending()
        self.assertEqual(len(pending), 1)
        self.assertIn("the mail server refused", pending[0].last_error)

    def test_a_message_is_given_up_on_after_too_many_attempts(self):
        from telemedicine.notifications import NotificationService
        transport = RecordingTransport(fail_with="never")
        service = NotificationService(store=InMemoryNotificationStore(),
                                     transport=transport, audit=self.audit,
                                     clock=self.clock)
        worker = DeliveryWorker(service, interval=1, sleeper=lambda seconds: None)
        service.queue(kind="appointment.booked", recipient_user_id="user-1",
                      subject="s", body="b")
        for _ in range(MAX_ATTEMPTS):
            worker.run_once()
        self.assertEqual(service.store.pending(), [])
        message = service.store.list_for_recipient("user-1")[0]
        self.assertEqual(message.status, "failed")

    def test_a_failure_does_not_stop_the_other_messages(self):
        class OneFails(RecordingTransport):
            def send(self, notification):
                if notification.recipient_user_id == "bad":
                    raise RuntimeError("no")
                super().send(notification)

        service = NotificationService(store=InMemoryNotificationStore(),
                                     transport=OneFails(), audit=self.audit,
                                     clock=self.clock)
        worker = DeliveryWorker(service, interval=1, sleeper=lambda seconds: None)
        service.queue(kind="appointment.booked", recipient_user_id="good", subject="s", body="b")
        service.queue(kind="appointment.booked", recipient_user_id="bad", subject="s", body="b")

        report = worker.run_once()
        self.assertEqual(report.sent, 1)
        self.assertEqual(report.failed, 1)

    def test_the_delivery_is_audited(self):
        self.queue()
        self.worker.run_once()
        actions = [entry.action for entry in self.audit.entries]
        self.assertIn("notification.sent", actions)


class SmtpTransportTest(unittest.TestCase):
    def setUp(self):
        self.directory = {"user-1": "ada@example.org"}
        self.transport = SmtpTransport(directory=lambda user_id: self.directory.get(user_id),
                                      host="mail.example.org", port=2525,
                                      sender="practice@example.org")

    def notification(self, recipient="user-1"):
        from telemedicine.notifications import Notification
        return Notification(notification_id=str(uuid.uuid4()),
                            kind="appointment.booked",
                            recipient_user_id=recipient,
                            subject="Your appointment is booked",
                            body="When: 2026-10-21 at 12:00 UTC",
                            created_at=NOW)

    def test_the_message_carries_the_recipient_the_subject_and_the_body(self):
        message = self.transport.build(self.notification(), "ada@example.org")
        self.assertEqual(message["To"], "ada@example.org")
        self.assertEqual(message["From"], "practice@example.org")
        self.assertEqual(message["Subject"], "Your appointment is booked")
        self.assertIn("2026-10-21 at 12:00 UTC", message.get_content())
        self.assertEqual(message["X-Telemedicine-Kind"], "appointment.booked")

    def test_a_recipient_with_no_address_is_an_error(self):
        with self.assertRaises(RuntimeError) as caught:
            self.transport.send(self.notification("nobody"))
        self.assertIn("no address", str(caught.exception))

    def test_the_message_is_sent_through_the_mail_server(self):
        with mock.patch("telemedicine.delivery.smtplib.SMTP") as server:
            self.transport.send(self.notification())
        server.assert_called_once()
        args, kwargs = server.call_args
        self.assertEqual(args[0], "mail.example.org")
        self.assertEqual(args[1], 2525)
        instance = server.return_value.__enter__.return_value
        instance.send_message.assert_called_once()

    def test_the_password_is_not_in_the_message(self):
        transport = SmtpTransport(directory=lambda user_id: "ada@example.org",
                                  host="mail.example.org", sender="practice@example.org",
                                  password="hunter2")
        message = transport.build(self.notification(), "ada@example.org")
        self.assertNotIn("hunter2", str(message))


class DirectoryTest(unittest.TestCase):
    def test_the_directory_looks_the_account_up(self):
        from telemedicine.auth import UserRepository
        users = UserRepository()
        users.save(account("user-1", "ada@example.org"))
        lookup = directory_from_users(users)
        self.assertEqual(lookup("user-1"), "ada@example.org")
        self.assertIsNone(lookup("user-nobody"))


class SettingsTest(unittest.TestCase):
    def test_the_mail_server_is_read_from_the_environment(self):
        from telemedicine.config import Settings
        settings = Settings.from_environment({
            "TELEMEDICINE_SMTP_HOST": "mail.example.org",
            "TELEMEDICINE_SMTP_PORT": "587",
            "TELEMEDICINE_SMTP_FROM": "practice@example.org",
            "TELEMEDICINE_SMTP_USERNAME": "practice",
            "TELEMEDICINE_SMTP_PASSWORD": "hunter2",
            "TELEMEDICINE_SMTP_TLS": "true",
            "TELEMEDICINE_DELIVERY_INTERVAL": "5",
        })
        self.assertEqual(settings.smtp_host, "mail.example.org")
        self.assertEqual(settings.smtp_port, 587)
        self.assertEqual(settings.smtp_from, "practice@example.org")
        self.assertEqual(settings.smtp_username, "practice")
        self.assertEqual(settings.smtp_password, "hunter2")
        self.assertTrue(settings.smtp_tls)
        self.assertEqual(settings.delivery_interval, 5)

    def test_the_defaults_are_sensible(self):
        from telemedicine.config import Settings
        settings = Settings.from_environment({})
        self.assertIsNone(settings.smtp_host)
        self.assertEqual(settings.smtp_port, 25)
        self.assertTrue(settings.smtp_tls)
        self.assertEqual(settings.delivery_interval, 30)

    def test_a_port_that_is_not_a_number_is_refused(self):
        from telemedicine.config import Settings
        with self.assertRaises(ValueError):
            Settings.from_environment({"TELEMEDICINE_SMTP_PORT": "not a number"})


class DeliveryScriptTest(unittest.TestCase):
    def test_it_refuses_to_run_without_a_database(self):
        import runpy
        import sys
        from telemedicine.config import Settings

        script = str(_repo_path("scripts/run_delivery.py"))
        with mock.patch.dict("os.environ", {"TELEMEDICINE_SMTP_HOST": "mail.example.org"},
                             clear=True):
            with mock.patch.object(sys, "argv", [script]):
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_path(script, run_name="__main__")
        self.assertNotEqual(caught.exception.code, 0)

    def test_it_refuses_to_run_without_a_mail_server(self):
        import runpy
        import sys

        script = str(_repo_path("scripts/run_delivery.py"))
        environment = {"TELEMEDICINE_DATABASE_URL": "postgresql://user@host/db"}
        with mock.patch.dict("os.environ", environment, clear=True):
            with mock.patch.object(sys, "argv", [script]):
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_path(script, run_name="__main__")
        self.assertNotEqual(caught.exception.code, 0)


class _FakeClock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now


def _repo_path(*parts):
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.joinpath(*parts)


if __name__ == "__main__":
    unittest.main()
