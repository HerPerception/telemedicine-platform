"""The FHIR R4 layer of the telemedicine application.

* :mod:`telemedicine.fhir.validation` — the R4 element tables and the
  checker for a resource, taken from the published R4 definitions.
* :mod:`telemedicine.fhir.serialization` — the mapping from the domain model
  onto FHIR resources, as declared in ``docs/fhir-mappings.md``.
* :mod:`telemedicine.fhir.repository` — the read and write paths, which
  authorize and audit every call.
* :mod:`telemedicine.fhir.server` — the HTTP surface.
"""

from telemedicine.fhir.repository import FhirRepository
from telemedicine.fhir.serialization import (
    capability_statement,
    encounter_resource,
    medication_request_resource,
    operation_outcome,
    patient_resource,
    practitioner_resource,
    appointment_resource,
)
from telemedicine.fhir.server import FhirApplication, Response, make_server, serve
from telemedicine.fhir.validation import validate_resource

__all__ = [
    "FhirApplication",
    "FhirRepository",
    "Response",
    "appointment_resource",
    "capability_statement",
    "encounter_resource",
    "make_server",
    "medication_request_resource",
    "operation_outcome",
    "patient_resource",
    "practitioner_resource",
    "serve",
    "validate_resource",
]
