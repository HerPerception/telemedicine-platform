#!/usr/bin/env python3
"""Send the queued notifications.

Usage:
    TELEMEDICINE_DATABASE_URL=... TELEMEDICINE_SMTP_HOST=... python3 scripts/run_delivery.py

The worker drains the outbox, sends what it can, and does it again. It is
meant to run as a sidecar or from a cron, next to the application.

The configuration comes from the environment:

    TELEMEDICINE_DATABASE_URL   the PostgreSQL connection string. Without
                                 it there is nothing to send.
    TELEMEDICINE_SMTP_HOST      the mail server.
    TELEMEDICINE_SMTP_PORT      its port (25)
    TELEMEDICINE_SMTP_FROM      the address the messages come from
    TELEMEDICINE_SMTP_USERNAME  the user to log in as, if the server wants one
    TELEMEDICINE_SMTP_PASSWORD  its password
    TELEMEDICINE_SMTP_TLS       whether to start TLS (true)
    TELEMEDICINE_DELIVERY_INTERVAL  how long to wait between passes (30s)

The password is read from the environment and never written anywhere: not
to the log, not to the audit trail, not to the outbox.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.application import build_application  # noqa: E402
from telemedicine.config import Settings  # noqa: E402
from telemedicine.delivery import (  # noqa: E402
    DeliveryWorker,
    SmtpTransport,
    directory_from_users,
)


def main(argv=None) -> int:
    settings = Settings.from_environment()

    if not settings.has_database:
        print("telemedicine: no database is configured, so there is no outbox to drain.",
              file=sys.stderr)
        return 1
    if not settings.smtp_host:
        print("telemedicine: no mail server is configured, so nothing can be sent.",
              file=sys.stderr)
        return 1

    application = build_application(settings)
    transport = SmtpTransport(
        directory=directory_from_users(application.auth.users),
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.smtp_from,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=settings.smtp_tls,
    )
    application.notifications.transport = transport

    worker = DeliveryWorker(application.notifications,
                            interval=settings.delivery_interval)
    print(f"telemedicine: sending from {settings.smtp_from} every "
          f"{settings.delivery_interval} seconds", flush=True)
    try:
        for report in worker.run_forever():
            if report.total:
                print(f"telemedicine: sent {report.sent}, failed {report.failed}, "
                      f"{report.remaining} still queued", flush=True)
    except KeyboardInterrupt:
        print("\ntelemedicine: stopping", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
