"""The delivery worker, and the transport that actually sends.

The outbox of ENG-011 queues the messages; something has to send them.
This is that something.

:class:`DeliveryWorker` drains the queue, on a schedule, and is what a
deployment runs as a sidecar or from a cron. It is deliberately small: it
does one thing, and it does it again.

:class:`~telemedicine.notifications.SmtpTransport` is the transport that
talks to a mail server. The standard library has ``smtplib``, so the
project gains no dependency for it.

**Delivery is at least once.** The worker sends a message and then marks it
sent, and a process that dies in between sends it again. A transport
therefore has to be willing to send the same message twice, which a
confirmation is.

**Nothing leaves Nigeria without a reason.** A message about a consultation is
health data, and the mail server may be in another country. So the transport
asks the :class:`~telemedicine.transfer.OutboundGuard` before it connects: a
transfer out of Nigeria needs a lawful basis under section 43 of the Nigeria
Data Protection Act 2023 and a written justification, and the guard refuses
the request without them and says which one is missing. A mail server in
Nigeria needs neither.
"""

from __future__ import annotations

import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable, List, Optional

from telemedicine.notifications import (
    Notification,
    NotificationService,
    NotificationTransport,
    DeliveryReport,
)
from telemedicine.transfer import OutboundGuard, TransferRequest


class AddressDirectory:
    """Where the address of an account comes from.

    It is a callable, so that the transport does not care whether the
    accounts are in memory or in the database. The one the application
    builds looks the account up in the user repository.
    """

    def __call__(self, user_id: str) -> Optional[str]:
        raise NotImplementedError


class SmtpTransport(NotificationTransport):
    """Sends the messages with a mail server.

    The body is plain text. A message about a consultation is health data,
    and a plain-text message is the least surprising thing to send and the
    easiest to read in every client.
    """

    def __init__(self, directory: Callable[[str], Optional[str]], host: str,
                 port: int = 25, sender: str = "telemedicine@localhost",
                 username: Optional[str] = None, password: Optional[str] = None,
                 start_tls: bool = False, timeout: int = 30,
                 guard: Optional[OutboundGuard] = None,
                 lawful_basis: Optional[str] = None,
                 justification: str = ""):
        self.directory = directory
        self.host = host
        self.port = port
        self.sender = sender
        self.username = username
        self.password = password
        self.start_tls = start_tls
        self.timeout = timeout
        # The gate on transfers out of Nigeria. Without one, the transport
        # sends to wherever it is told to; a deployment wires one in.
        self.guard = guard
        # The basis and the justification for sending health data to this
        # mail server. They are only needed when the server is outside
        # Nigeria.
        self.lawful_basis = lawful_basis
        self.justification = justification

    def send(self, notification: Notification) -> None:
        address = self.directory(notification.recipient_user_id)
        if not address:
            raise RuntimeError(
                f"the account {notification.recipient_user_id} has no address to send to")
        # Before anything is sent, the gate decides whether it may be.
        self.check_transfer(notification, address)
        message = self.build(notification, address)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as client:
            if self.start_tls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password or "")
            client.send_message(message)

    def check_transfer(self, notification: Notification, address: str) -> None:
        """Ask the gate whether this message may leave the country.

        Nothing is sent when the gate refuses, and the refusal says which
        of the two things is missing.
        """
        if self.guard is None:
            return
        self.guard.permit(
            TransferRequest(
                destination_country="",
                recipient=address,
                data_categories=[notification.kind],
                lawful_basis=self.lawful_basis,
                justification_text=self.justification,
            ),
            host=self.host,
            service="smtp",
            user_id=notification.recipient_user_id,
        )

    def build(self, notification: Notification, address: str) -> EmailMessage:
        """The message that would be sent. Kept apart so that it can be read."""
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = address
        message["Subject"] = notification.subject
        # The kind is a header, so that a mail server can route or filter on
        # it without reading the body.
        message["X-Telemedicine-Kind"] = notification.kind
        message.set_content(notification.body)
        return message


@dataclass
class DeliveryWorker:
    """Drains the outbox, again and again."""

    service: NotificationService
    interval: int = 30
    sleeper: Callable[[float], None] = time.sleep

    def run_once(self, limit: int = 100) -> DeliveryReport:
        """One pass over the queue."""
        return self.service.deliver(limit=limit)

    def run_forever(self, max_iterations: Optional[int] = None) -> List[DeliveryReport]:
        """Pass after pass, until stopped.

        ``max_iterations`` is what the tests use; without it this runs until
        the process is stopped.
        """
        reports: List[DeliveryReport] = []
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            reports.append(self.run_once())
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            self.sleeper(self.interval)
        return reports


def directory_from_users(users) -> Callable[[str], Optional[str]]:
    """An address directory over a user repository."""
    def lookup(user_id: str) -> Optional[str]:
        account = users.get_by_id(user_id) if users is not None else None
        return account.email if account is not None else None
    return lookup
