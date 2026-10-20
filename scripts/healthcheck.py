#!/usr/bin/env python3
"""Is the application ready to serve?

Usage:
    python3 scripts/healthcheck.py

The check asks two questions:

* **is the server answering?** — the metadata endpoint of the FHIR API, which
  is public and touches nothing;
* **is the database there, and does it have the schema?** — the tables the
  application needs, and the schema applied.

Exit status is 0 when both are true, and 1 when either is not. It prints what
it found, because a health check that says only "unhealthy" is a health check
that costs an hour.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.config import Settings  # noqa: E402

TIMEOUT = 5


def check_server(host: str, port: int) -> bool:
    """The metadata endpoint answers."""
    url = f"http://{host}:{port}/fhir/metadata"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            if response.status != 200:
                print(f"the server answered {response.status} for {url}", file=sys.stderr)
                return False
            payload = json.loads(response.read().decode("utf-8"))
            if payload.get("resourceType") != "CapabilityStatement":
                print(f"the server did not answer with a CapabilityStatement: {url}",
                      file=sys.stderr)
                return False
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"the server is not answering at {url}: {error}", file=sys.stderr)
        return False
    return True


def check_database(settings: Settings) -> bool:
    """The database is reachable and the schema has been applied."""
    if not settings.has_database:
        print("no database is configured", file=sys.stderr)
        return False
    from telemedicine.persistence.database import Database

    try:
        database = Database(settings.database_url)
        database.check_connection()
        missing = database.missing_tables()
    except Exception as error:
        print(f"the database is not usable: {error}", file=sys.stderr)
        return False
    if missing:
        print(f"the schema has not been applied: {', '.join(missing)} are missing. "
              "Run scripts/apply_schema.py.", file=sys.stderr)
        return False
    return True


def main(argv=None) -> int:
    settings = Settings.from_environment()
    # The health check runs inside the container, where the server listens on
    # the loopback as well as on every interface.
    host = os.environ.get("TELEMEDICINE_HEALTHCHECK_HOST", "127.0.0.1")
    port = int(os.environ.get("TELEMEDICINE_HEALTHCHECK_PORT", settings.port))

    healthy = check_server(host, port)
    healthy = check_database(settings) and healthy

    if healthy:
        print("the application is serving, and the database has the schema")
        return 0
    print("the application is not ready", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
