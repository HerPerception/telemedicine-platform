# ENG-006: expose the FHIR R4 API

The five core resources are now readable and writable over HTTP, with the
authorization rules and the audit trail of ENG-002 behind every call.

* telemedicine/fhir/validation.py - the R4 element tables, cardinalities and
  value sets, and the checker for a resource. Moved out of
  scripts/validate_fhir_examples.py, which is now a thin front end, so
  that the API and the command-line tool check against one implementation.
* telemedicine/fhir/serialization.py - the mapping from the domain model onto
  FHIR resources, exactly as docs/fhir-mappings.md declares it.
* telemedicine/fhir/repository.py - the read and write paths. They translate
  a FHIR resource into the arguments the domain services expect and call
  them, so every access is authorized and audited in one place.
* telemedicine/fhir/server.py - the HTTP surface. Every resource it is about
  to send is checked against the profile first; a resource that does not
  satisfy it is never sent. The errors are OperationOutcomes with the right
  status: 400, 401, 403, 404, 405, 409 and 500.

A clinical record is never deleted: DELETE answers 405 and a cancellation is
a status. Booking a slot that has just been taken answers 409, which needed
a new ConflictError. A patient reads their own record and nobody else's; a
practitioner reads the patients they treat, because the relationship comes
from an appointment or an encounter and not from a flag; only the clinician
who treated the encounter may issue a prescription against it.

Amendments to earlier features, recorded in the design document and in the
coordination log: the records carry the fields ENG-001's schema defines and
the mapping projects; the read and write paths for practitioners, patients,
encounters and prescriptions are authorized and audited like the rest; three
authorization rules for the write paths; and the R4 tables moved into the
package.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

The API is served by the standard library's http.server over plain HTTP,
with no persistence behind it; both are recorded in the design document.

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
