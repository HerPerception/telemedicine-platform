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

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


@dataclass(frozen=True)
class Settings:
    """What the application is configured with."""

    database_url: Optional[str] = None
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    audit_anchor: Optional[str] = None

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
        return cls(database_url=database_url, host=host, port=port, audit_anchor=anchor)

    def describe(self) -> str:
        """A description of the settings, without the secret."""
        where = "the database" if self.has_database else "memory (no database configured)"
        return f"{where}, listening on {self.host}:{self.port}"
