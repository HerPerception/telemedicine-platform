"""The application: the services, wired together.

Until now every part of the application had to be assembled by hand — the
records service, the slots, the booking service, the prescriptions, the
authentication, the video rooms and the two HTTP surfaces. That is fine for
a test and wrong for a deployment, where the wiring has to be right and
identical every time.

This module is that wiring, in one place, from one set of settings:

* **with a database** — every record, the audit log, the lockout counter, the
  accounts, the sessions and the prescription documents live in PostgreSQL, and
  the application can run in more than one instance;
* **without one** — the same services, with the records in memory. That is
  what the tests use, and it is why the suite still runs on a machine with no
  database.

The wiring is also the place where the audit log is shared: one log, written
by every service, is the only way the trail is a trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from telemedicine.audit import AuditLog
from telemedicine.audit_anchor import AnchoredAuditLog, FileAuditAnchor
from telemedicine.auth import AuthService
from telemedicine.booking import BookingService, SlotService
from telemedicine.config import Settings
from telemedicine.fhir.repository import FhirRepository
from telemedicine.fhir.server import ApplicationRouter, FhirApplication
from telemedicine.persistence.audit_store import PostgresAuditLog
from telemedicine.persistence.clinical_store import PostgresClinicalRepository
from telemedicine.persistence.database import Database
from telemedicine.persistence.document_store import PostgresDocumentStore
from telemedicine.persistence.lockout import InMemoryLockoutStore, PostgresLockoutStore
from telemedicine.persistence.notification_store import PostgresNotificationStore
from telemedicine.notifications import NotificationService
from telemedicine.prescriptions import PrescriptionService
from telemedicine.records import RecordsService
from telemedicine.video import VideoService
from telemedicine.video_api import VideoApplication


@dataclass
class Application:
    """Everything the application is made of."""

    settings: Settings
    database: Optional[Database]
    audit: object
    auth: AuthService
    records: RecordsService
    slots: SlotService
    booking: BookingService
    prescriptions: PrescriptionService
    notifications: NotificationService
    video: VideoService
    fhir: FhirApplication
    video_api: VideoApplication

    @property
    def http(self) -> ApplicationRouter:
        """The two HTTP surfaces, on one router."""
        return ApplicationRouter({"/fhir": self.fhir, "/video": self.video_api})

    def apply_schema(self):
        """Apply the schema. Only possible with a database."""
        if self.database is None:
            raise RuntimeError("there is no database to apply the schema to")
        return self.database.apply_schema()

    def check(self) -> None:
        """Check that the application is ready to serve.

        A deployment that believes it has a database and does not is worse
        than one that refuses to start, so the check happens before the
        server does.
        """
        if self.database is None:
            return
        self.database.check_connection()
        missing = self.database.missing_tables()
        if missing:
            raise RuntimeError(
                "the schema has not been applied: the tables "
                f"{', '.join(missing)} are missing. Run "
                "scripts/apply_schema.py first.")


def build_application(settings: Optional[Settings] = None,
                      clock=None, verify: bool = True) -> Application:
    """Assemble the application from the settings.

    With a database in the settings, every store is the database one. Without
    one, they are the in-memory ones and the application keeps its records in
    the memory of the process.

    When a database is configured, it is checked before the application is
    handed back, unless ``verify`` is turned off. Starting an application
    that believes it has a database and does not would put the records of one
    request in memory and the records of the next in the database.
    """
    settings = settings if settings is not None else Settings.from_environment()
    database = Database(settings.database_url) if settings.has_database else None

    anchor_store = None
    if settings.audit_anchor:
        anchor_store = FileAuditAnchor(settings.audit_anchor)

    if database is not None:
        from telemedicine.persistence.account_store import (
            PostgresSessionStore,
            PostgresUserRepository,
        )
        audit = PostgresAuditLog(database)
        lockout = PostgresLockoutStore(database)
        users = PostgresUserRepository(database)
        sessions = PostgresSessionStore(database)
        documents = PostgresDocumentStore(database)
        clinical = PostgresClinicalRepository(database)
        slot_store = clinical
        notification_store = PostgresNotificationStore(database)
    else:
        audit = AuditLog(clock=clock) if clock is not None else AuditLog()
        lockout = InMemoryLockoutStore()
        users = None
        sessions = None
        documents = None
        clinical = None
        slot_store = None
        notification_store = None

    if anchor_store is not None:
        # The chain is published outside the database, so that a chain
        # rewritten from the beginning can be told apart from an untouched
        # one. The internal check cannot see that difference.
        audit = AnchoredAuditLog(audit, anchor_store)

    notifications = NotificationService(store=notification_store, audit=audit)

    auth = AuthService(users=users, audit=audit, sessions=sessions, lockout=lockout)
    records = RecordsService(audit=audit, repository=clinical)
    slots = SlotService(audit=audit, repository=slot_store)
    booking = BookingService(slots, audit=audit, records=records, accounts=auth.users,
                             notifications=notifications)
    prescriptions = PrescriptionService(records, documents=documents, audit=audit,
                                        notifications=notifications)
    video = VideoService(records, audit=audit)

    fhir = FhirApplication(FhirRepository(records, booking, prescriptions), auth,
                            trust_forwarded_for=settings.trust_forwarded_for)
    video_api = VideoApplication(video, auth,
                                 trust_forwarded_for=settings.trust_forwarded_for)

    application = Application(
        settings=settings,
        database=database,
        audit=audit,
        auth=auth,
        records=records,
        slots=slots,
        booking=booking,
        prescriptions=prescriptions,
        notifications=notifications,
        video=video,
        fhir=fhir,
        video_api=video_api,
    )
    if verify and database is not None:
        application.check()
    return application
