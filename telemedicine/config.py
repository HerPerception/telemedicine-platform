"""The settings of the application.

Everything is read from the environment, because a deployment configures a
process from the outside and a file on disk is one more thing to keep in
step. The names are prefixed so that they cannot collide with the rest of the
environment of a machine they run on.

============================  ==========================================
``TELEMEDICINE_DATABASE_URL``  the PostgreSQL connection string. **Without
                              it the application keeps its records in
                              memory**, which is right for the tests and
                              wrong for a deployment.
``TELEMEDICINE_HOST``          the interface to listen on. Default
                              ``127.0.0.1``, which is the safe one: a
                              server that listens on every interface by
                              accident is a server that answers on a
                              network it was never meant to.
``TELEMEDICINE_PORT``          the port to listen on. Default ``8080``.
``TELEMEDICINE_SMTP_HOST``      the mail server the delivery worker sends
                              through.
``TELEMEDICINE_SMTP_PORT``      its port. Default 25.
``TELEMEDICINE_SMTP_FROM``      the address the messages come from.
``TELEMEDICINE_SMTP_USERNAME``  the user to log in as, if the server wants
                              one.
``TELEMEDICINE_SMTP_PASSWORD``  its password. It is read from the
                              environment and written nowhere.
``TELEMEDICINE_SMTP_TLS``       whether to start TLS. Default true.
``TELEMEDICINE_DELIVERY_INTERVAL``  how long the delivery worker waits
                              between passes. Default 30 seconds.
``TELEMEDICINE_TRUST_FORWARDED_FOR``  whether to believe the address a
                              proxy says the request came from. Off by
                              default: the header is set by whoever sends
                              the request, so it is only safe behind a
                              proxy that replaces it. It is what the
                              login lockout counts per address.
``TELEMEDICINE_AUDIT_ANCHOR``  the file the audit chain is anchored to.
                              Without it the chain is not anchored, and
                              a chain rewritten from the beginning cannot
                              be told apart from an untouched one.
============================  ==========================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

ENV_DATABASE_URL = "TELEMEDICINE_DATABASE_URL"
ENV_HOST = "TELEMEDICINE_HOST"
ENV_PORT = "TELEMEDICINE_PORT"
ENV_AUDIT_ANCHOR = "TELEMEDICINE_AUDIT_ANCHOR"
ENV_TRUST_FORWARDED_FOR = "TELEMEDICINE_TRUST_FORWARDED_FOR"
ENV_SMTP_HOST = "TELEMEDICINE_SMTP_HOST"
ENV_SMTP_PORT = "TELEMEDICINE_SMTP_PORT"
ENV_SMTP_FROM = "TELEMEDICINE_SMTP_FROM"
ENV_SMTP_USERNAME = "TELEMEDICINE_SMTP_USERNAME"
ENV_SMTP_PASSWORD = "TELEMEDICINE_SMTP_PASSWORD"
ENV_SMTP_TLS = "TELEMEDICINE_SMTP_TLS"
ENV_DELIVERY_INTERVAL = "TELEMEDICINE_DELIVERY_INTERVAL"
# ENG-018: the gate on transfers out of Nigeria.
ENV_TRANSFER_SERVICES = "TELEMEDICINE_TRANSFER_SERVICES"
ENV_SMTP_LAWFUL_BASIS = "TELEMEDICINE_SMTP_LAWFUL_BASIS"
ENV_SMTP_JUSTIFICATION = "TELEMEDICINE_SMTP_JUSTIFICATION"
# ENG-019: the media server the practice runs itself, in Nigeria.
ENV_LIVEKIT_HOST = "TELEMEDICINE_LIVEKIT_HOST"
ENV_LIVEKIT_URL = "TELEMEDICINE_LIVEKIT_URL"
ENV_LIVEKIT_API_KEY = "TELEMEDICINE_LIVEKIT_API_KEY"
ENV_LIVEKIT_API_SECRET = "TELEMEDICINE_LIVEKIT_API_SECRET"
ENV_RECORDING_ENABLED = "TELEMEDICINE_RECORDING_ENABLED"
ENV_RECORDING_CONSENT_REQUIRED = "TELEMEDICINE_RECORDING_CONSENT_REQUIRED"
ENV_RECORDING_BUCKET = "TELEMEDICINE_RECORDING_BUCKET"
# ENG-020: SMART on FHIR. Off by default: a practice that is not connected
# to a hospital does not need it, and the ordinary sign-in is enough.
ENV_SMART_FHIR_ENABLED = "TELEMEDICINE_SMART_FHIR_ENABLED"
ENV_SMART_CLIENTS = "TELEMEDICINE_SMART_CLIENTS"
ENV_SMART_STATE_SECRET = "TELEMEDICINE_SMART_STATE_SECRET"
# ENG-022: the demo mode. It is **on by default**, because the practice has
# no legal adviser yet and the documents say so on their face.
ENV_DEMO_MODE = "TELEMEDICINE_DEMO_MODE"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


@dataclass(frozen=True)
class Settings:
    """What the application is configured with."""

    database_url: Optional[str] = None
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    audit_anchor: Optional[str] = None
    trust_forwarded_for: bool = False
    smtp_host: Optional[str] = None
    smtp_port: int = 25
    smtp_from: str = "telemedicine@localhost"
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_tls: bool = True
    delivery_interval: int = 30
    # Where the external services are described. Each one says where it is,
    # and what the practice has recorded for sending data to it.
    transfer_services: Optional[str] = None
    # The basis and the justification for sending health data to the mail
    # server. They are only needed when it is outside Nigeria.
    smtp_lawful_basis: Optional[str] = None
    smtp_justification: str = ""
    # ENG-019: the media server. The host is the practice's own server, in
    # Nigeria; the URL is what the browser connects to.
    livekit_host: Optional[str] = None
    livekit_url: Optional[str] = None
    livekit_api_key: Optional[str] = None
    livekit_api_secret: Optional[str] = None
    # Recording is off by default, and needs the patient's consent even when
    # it is on.
    recording_enabled: bool = False
    recording_consent_required: bool = True
    recording_bucket: Optional[str] = None
    # ENG-020: SMART on FHIR. Off by default, and the endpoints are not
    # registered at all while it is off.
    # None means "not set in the environment", and the configuration file
    # decides. True or False overrides it.
    smart_fhir_enabled: Optional[bool] = None
    smart_clients: Optional[str] = None
    smart_state_secret: Optional[str] = None
    # ENG-022: on by default. Every document says on its face that it is not
    # for real patients, until an adviser has signed and the practice turns
    # it off.
    demo_mode: bool = True

    @property
    def has_database(self) -> bool:
        """Whether the application keeps its records in a database."""
        return bool(self.database_url)

    @classmethod
    def from_environment(cls, environment=None) -> "Settings":
        """Read the settings from the environment."""
        environment = environment if environment is not None else os.environ
        database_url = (environment.get(ENV_DATABASE_URL) or "").strip() or None
        host = (environment.get(ENV_HOST) or "").strip() or DEFAULT_HOST
        port_text = (environment.get(ENV_PORT) or "").strip()
        try:
            port = int(port_text) if port_text else DEFAULT_PORT
        except ValueError as error:
            raise ValueError(f"{ENV_PORT} must be a number, not '{port_text}'") from error
        anchor = (environment.get(ENV_AUDIT_ANCHOR) or "").strip() or None
        forwarded = (environment.get(ENV_TRUST_FORWARDED_FOR) or "").strip().lower()
        tls = (environment.get(ENV_SMTP_TLS) or "").strip().lower()
        smtp_host = (environment.get(ENV_SMTP_HOST) or "").strip() or None
        smtp_from = (environment.get(ENV_SMTP_FROM) or "").strip() or "telemedicine@localhost"
        smtp_username = (environment.get(ENV_SMTP_USERNAME) or "").strip() or None
        smtp_password = (environment.get(ENV_SMTP_PASSWORD) or "").strip() or None
        port_text = (environment.get(ENV_SMTP_PORT) or "").strip()
        interval_text = (environment.get(ENV_DELIVERY_INTERVAL) or "").strip()
        try:
            smtp_port = int(port_text) if port_text else 25
            delivery_interval = int(interval_text) if interval_text else 30
        except ValueError as error:
            raise ValueError(
                f"the mail server port and the delivery interval must be numbers: {error}"
            ) from error
        livekit_host = (environment.get(ENV_LIVEKIT_HOST) or "").strip() or None
        livekit_url = (environment.get(ENV_LIVEKIT_URL) or "").strip() or None
        livekit_api_key = (environment.get(ENV_LIVEKIT_API_KEY) or "").strip() or None
        livekit_api_secret = (environment.get(ENV_LIVEKIT_API_SECRET) or "").strip() or None
        recording_bucket = (environment.get(ENV_RECORDING_BUCKET) or "").strip() or None
        smart_text = (environment.get(ENV_SMART_FHIR_ENABLED) or "").strip().lower()
        smart_enabled = (smart_text in ("1", "true", "yes", "on")
                         if smart_text else None)
        smart_clients = (environment.get(ENV_SMART_CLIENTS) or "").strip() or None
        smart_state_secret = (environment.get(ENV_SMART_STATE_SECRET) or "").strip() or None
        demo = (environment.get(ENV_DEMO_MODE) or "").strip().lower()
        recording = (environment.get(ENV_RECORDING_ENABLED) or "").strip().lower()
        recording_consent = (environment.get(ENV_RECORDING_CONSENT_REQUIRED)
                             or "").strip().lower()
        transfer_services = (environment.get(ENV_TRANSFER_SERVICES) or "").strip() or None
        smtp_lawful_basis = (environment.get(ENV_SMTP_LAWFUL_BASIS) or "").strip() or None
        smtp_justification = (environment.get(ENV_SMTP_JUSTIFICATION) or "").strip()
        return cls(database_url=database_url, host=host, port=port, audit_anchor=anchor,
                   trust_forwarded_for=forwarded in ("1", "true", "yes", "on"),
                   smtp_host=smtp_host, smtp_port=smtp_port, smtp_from=smtp_from,
                   smtp_username=smtp_username, smtp_password=smtp_password,
                   smtp_tls=True if not tls else tls in ("1", "true", "yes", "on"),
                   delivery_interval=delivery_interval,
                   transfer_services=transfer_services,
                   smtp_lawful_basis=smtp_lawful_basis,
                   smtp_justification=smtp_justification,
                   livekit_host=livekit_host, livekit_url=livekit_url,
                   livekit_api_key=livekit_api_key,
                   livekit_api_secret=livekit_api_secret,
                   recording_enabled=recording in ("1", "true", "yes", "on"),
                   recording_consent_required=(recording_consent in
                                               ("1", "true", "yes", "on")
                                               if recording_consent else True),
                   recording_bucket=recording_bucket,
                   smart_fhir_enabled=smart_enabled in ("1", "true", "yes", "on"),
                   smart_clients=smart_clients,
                   smart_state_secret=smart_state_secret,
                   demo_mode=demo in ("1", "true", "yes", "on") if demo else True)

    def describe(self) -> str:
        """A description of the settings, without the secret."""
        where = "the database" if self.has_database else "memory (no database configured)"
        return f"{where}, listening on {self.host}:{self.port}"
