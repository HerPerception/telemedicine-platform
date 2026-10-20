#!/usr/bin/env python3
"""Validate the ENG-001 example FHIR R4 resources.

Usage:
    python3 scripts/validate_fhir_examples.py [EXAMPLES_DIR] [--json]

The rules this checks are declared in ``docs/fhir-mappings.md`` and are
implemented in :mod:`telemedicine.fhir.validation`, which the API layer also
uses to check the resources it serves. This script is the command-line
front end for that module.

Exit status is 0 when no errors are found and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when the script is run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemedicine.fhir.validation import (  # noqa: E402
    ADMINISTRATIVE_GENDER,
    ALLOWED_EXTENSIONS,
    ALLOWED_IDENTIFIER_SYSTEMS,
    APPOINTMENT_STATUS,
    CANONICAL_BASE,
    CHOICE_VARIANTS,
    ENCOUNTER_CLASS,
    ENCOUNTER_STATUS,
    ENCOUNTER_TYPE,
    MEDICATION_REQUEST_INTENT,
    MEDICATION_REQUEST_STATUS,
    PARTICIPANT_REQUIRED,
    PARTICIPANT_TYPE,
    PARTICIPATION_STATUS,
    PROFILE_REQUIRED,
    PROFILES,
    SLOT_STATUS,
    build_example_index,
    load_examples,
    validate_directory,
    validate_resource,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_dir = Path(__file__).resolve().parent.parent / "docs" / "fhir" / "examples"
    parser.add_argument("directory", nargs="?", type=Path, default=default_dir,
                        help="directory holding the example resources")
    parser.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = parser.parse_args(argv)

    errors, resources = validate_directory(args.directory)

    if args.json:
        print(json.dumps({
            "directory": str(args.directory),
            "resources": sorted(resources),
            "errors": errors,
            "valid": not errors,
        }, indent=2))
        return 1 if errors else 0

    print(f"Checked {len(resources)} example resources in {args.directory}")
    for name in sorted(resources):
        resource = resources[name]
        print(f"  {name}: {resource.get('resourceType')}/{resource.get('id')}")
    if errors:
        print(f"\n{len(errors)} problem(s) found:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("\nAll example resources satisfy the declared ENG-001 mapping rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
