#!/usr/bin/env python3
"""Inventory the external services this project talks to.

Usage:
    python3 scripts/audit_external_services.py [--dsn DSN] [--services FILE]

    TELEMEDICINE_DATABASE_URL=... python3 scripts/audit_external_services.py

**What this is for.** Section 41(1) of the Nigeria Data Protection Act 2023
forbids transferring personal data from Nigeria to another country unless
the recipient has an adequate level of protection, or one of the conditions
in section 43 applies. Section 41(2) requires the basis for the transfer to
be recorded.

So the practice needs to know, in one place: which services the application
can send patient data to, which country each of them is in, whether the
transfer to it is currently allowed, and whether anything has actually been
sent.

The command prints that list. It reads:

* ``config/external_services.yaml`` — the services, their countries, and the
  basis and justification recorded for each of them;
* ``.env`` — whether a service has been configured here at all;
* ``package.json`` — the same, for a JavaScript build;
* the ``transfer_logs`` table — whether anything has been sent.

Exit status is 0 when the command did what it was asked to do, and 1 when
something is wrong with the configuration — not when a service is blocked. A
service that is blocked is the expected state until the practice's adviser
confirms the numbers, and it must not look like a failure of the command.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.transfer import (  # noqa: E402
    DEFAULT_SERVICES_PATH,
    ExternalServiceRegistry,
)
from telemedicine.yaml_lite import ConfigurationError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--services", type=Path, default=DEFAULT_SERVICES_PATH,
                        help="the external services file")
    parser.add_argument("--dsn", default=None,
                        help="the PostgreSQL connection string. Without it, the "
                             "transfer log is not read")
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env",
                        help="the environment file to scan")
    parser.add_argument("--package-json", type=Path,
                        default=REPO_ROOT / "package.json",
                        help="the package manifest to scan")
    return parser


def scan_env(path: Path) -> str:
    """The environment file, as text, or an empty string."""
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def scan_package_json(path: Path) -> dict:
    """The dependencies of a package manifest, as text, or an empty string."""
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    parts = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        for name, version in (manifest.get(section) or {}).items():
            parts.append(f"{name}@{version}")
    return {"text": "\n".join(parts), "names": list(manifest.get("dependencies") or {})}


def configured_in_env(text: str, service) -> bool:
    """Whether the environment file mentions this service."""
    if not text:
        return False
    lowered = text.lower()
    if service.host.lower() in lowered:
        return True
    token = service.name.lower().replace("_", "").replace("-", "")
    for word in re.split(r"[^a-z0-9]+", service.name.lower()):
        if len(word) > 3 and word in lowered:
            return True
    return token in lowered.replace("_", "").replace("-", "")


def configured_in_package_json(manifest: dict, service) -> bool:
    """Whether the package manifest depends on this service."""
    if not manifest:
        return False
    text = manifest.get("text", "").lower()
    name = service.name.lower()
    host = service.host.lower().split(".")[0]
    return name in text or host in text


def transfer_log_for(destination: str, dsn):
    """What has been sent to this destination, if the log can be read."""
    if not dsn:
        return None
    from telemedicine.persistence.database import Database
    from telemedicine.persistence.transfer_store import PostgresTransferLog
    return PostgresTransferLog(Database(dsn)).for_destination(destination)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        registry = ExternalServiceRegistry.from_file(args.services)
    except ConfigurationError as error:
        print(f"The external services could not be read: {error}", file=sys.stderr)
        return EXIT_ERROR

    env_text = scan_env(args.env)
    manifest = scan_package_json(args.package_json)

    print("External services")
    print(f"  configuration: {args.services}")
    print(f"  environment file: {args.env}"
          + ("" if args.env.is_file() else " (there is none)"))
    print(f"  package manifest: {args.package_json}"
          + ("" if args.package_json.is_file() else " (there is none)"))
    print(f"  transfer log: {'the database' if args.dsn else 'not read (no --dsn)'}")
    print()

    blocked = 0
    for service in registry.services():
        permitted = service.permitted
        if not permitted:
            blocked += 1
        entries = None
        try:
            entries = transfer_log_for(service.host, args.dsn)
        except Exception as error:
            entries = None
            print(f"  (the transfer log could not be read: {error})")

        sent = len(entries) if entries is not None else None
        print(f"{service.name}")
        print(f"  host:      {service.host}")
        print(f"  country:   {service.destination_country}"
              + ("  (Nigeria: nothing leaves the country)"
                 if service.in_nigeria else ""))
        print(f"  state:     {'allowed' if permitted else 'BLOCKED'}"
              + ("" if permitted else f"  — {service.reason}"))
        print(f"  basis:     {service.lawful_basis or 'none recorded'}")
        print(f"  why:       {service.justification or 'none recorded'}")
        print(f"  configured here: "
              + ("yes" if configured_in_env(env_text, service) else "no")
              + (", in package.json"
                 if configured_in_package_json(manifest, service) else ""))
        print(f"  transfer log: "
              + ("nothing sent" if sent == 0
                 else f"{sent} transfers" if sent
                 else "not readable"))
        print()

    print(f"{len(registry.services())} services, {blocked} of them blocked until a "
          f"justification is recorded.")
    if blocked:
        print("A blocked service is the expected state: the practice has not yet "
              "confirmed the transfer, and the gate refuses it rather than "
              "sending patient data abroad without a reason.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
