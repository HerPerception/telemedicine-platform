#!/usr/bin/env python3
"""Run the application.

Usage:
    python3 scripts/run_server.py

The configuration comes from the environment:

    TELEMEDICINE_DATABASE_URL   the PostgreSQL connection string. Without
                                it the application keeps its records in
                                memory, which is not a deployment.
    TELEMEDICINE_HOST           the interface to listen on (127.0.0.1)
    TELEMEDICINE_PORT           the port to listen on (8080)

The schema is **not** applied here. Applying it is a deployment step, done
once, with ``scripts/apply_schema.py`` — a process that starts should not
change the shape of the database underneath it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.application import build_application  # noqa: E402
from telemedicine.config import Settings  # noqa: E402
from telemedicine.fhir.server import make_server  # noqa: E402


def main(argv=None) -> int:
    settings = Settings.from_environment()
    application = build_application(settings)

    if not settings.has_database:
        print("WARNING: no database is configured, so the records of this process")
        print("         are in its memory and are lost when it stops. Set")
        print("         TELEMEDICINE_DATABASE_URL for anything but a demo.")
    print(f"telemedicine: {settings.describe()}")
    print(f"telemedicine: FHIR R4 API under /fhir, video rooms under /video")

    server = make_server(application.http, settings.host, settings.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ntelemedicine: stopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
