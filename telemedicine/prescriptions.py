"""E-prescriptions: issuance, viewing, the document, and the audit trail.

This is the ENG-005 layer. It builds on what ENG-002 already provides — the
authorization rules for ``MedicationRequest`` and the audited
:meth:`~telemedicine.records.RecordsService.issue_prescription` and
``read_prescription`` — and adds what a prescription needs to be a real
document:

* a printable document, rendered as a PDF with no third-party dependency, so
  that the patient can download and print it;
* a document store that keeps the bytes and a SHA-256 checksum, so that a
  download can be checked for tampering;
* the prescription lifecycle (``draft`` → ``active`` → ``completed`` /
  ``cancelled`` / ``stopped``), with an audit entry for every change.

Everything that touches a prescription goes through the authorization rules
and leaves an audit entry, whether it succeeded or was refused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, NamedTuple, Optional, Tuple, Union

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_ERROR, OUTCOME_SUCCESS, AuditLog
from telemedicine.authorization import Action, ResourceType
from telemedicine.errors import AuthorizationError, ValidationError
from telemedicine.medications import validate_dispensing_identity
from telemedicine.models import UserAccount
from telemedicine.records import PatientRecord, PractitionerRecord, Prescription, RecordsService

# Prescription status values, as in the FHIR MedicationRequestStatus value set.
STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"
STATUS_ON_HOLD = "on-hold"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_STOPPED = "stopped"

ALLOWED_STATUSES = frozenset({
    STATUS_DRAFT, STATUS_ACTIVE, STATUS_ON_HOLD, STATUS_COMPLETED,
    STATUS_CANCELLED, STATUS_STOPPED,
})

# The transitions a prescription may make. A prescription is not a record that
# can be edited in place: it moves through a small, explicit set of states.
ALLOWED_TRANSITIONS = {
    STATUS_DRAFT: {STATUS_ACTIVE, STATUS_CANCELLED},
    STATUS_ACTIVE: {STATUS_ON_HOLD, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_STOPPED},
    STATUS_ON_HOLD: {STATUS_ACTIVE, STATUS_CANCELLED, STATUS_STOPPED},
    STATUS_COMPLETED: frozenset(),
    STATUS_CANCELLED: frozenset(),
    STATUS_STOPPED: frozenset(),
}

CONTENT_TYPE_PDF = "application/pdf"

# Audit actions added by this feature.
ACTION_DOWNLOAD = "prescription.download"
ACTION_STATUS_CHANGE = "prescription.status_change"
ACTION_DOCUMENT_RENDER = "prescription.document_render"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------


def _escape_pdf_text(text: str) -> str:
    """Escape a string for a PDF literal string.

    Parentheses and backslashes are escaped, control characters become
    spaces, and characters outside the WinAnsi range are replaced rather
    than written raw, so that the document always renders.
    """
    out: List[str] = []
    for char in text:
        if char in "()\\":
            out.append("\\" + char)
        elif 32 <= ord(char) < 127:
            out.append(char)
        elif char in "\n\r\t":
            out.append(" ")
        elif 160 <= ord(char) <= 255:
            out.append("\\%03o" % ord(char))
        else:
            out.append("?")
    return "".join(out)


@dataclass(frozen=True)
class PdfLine:
    """One line of a document, with the style it is printed in.

    The prescription prints the medicine large and bold, because a pharmacist
    has to read the right product off the page without hunting for it, and
    the brand and the registration number are what they read it by.
    """

    text: str
    size: int = 11
    bold: bool = False
    # Points of space above the line.
    space_before: int = 0


def render_pdf(lines: List[Union[str, PdfLine]]) -> bytes:
    """Render a list of text lines as a single-page PDF.

    The output is a minimal but well-formed PDF 1.4 file: a catalog, a page
    tree, one page, one content stream and the Helvetica font, with a
    cross-reference table and a trailer. Text is written uncompressed, which
    keeps the file readable and lets a test assert on its contents.

    A line may be a plain string, or a :class:`PdfLine` when it is to be
    printed large or in bold. The bold face is Helvetica-Bold, and it is
    only put in the page's resources when a line uses it.

    This is a deliberately small renderer: it does one thing, with no
    dependency on a PDF library.
    """
    styled = [line if isinstance(line, PdfLine) else PdfLine(str(line)) for line in lines]
    bold_used = any(line.bold for line in styled)

    content_lines = ["BT", "/F1 11 Tf", "1 0 0 1 56 786 Tm", "14 TL"]
    for line in styled:
        if line.space_before:
            content_lines.append("0 -%d Td" % line.space_before)
        content_lines.append("%s %d Tf" % ("/F2" if line.bold else "/F1", line.size))
        content_lines.append("%d TL" % int(round(line.size * 1.3)))
        content_lines.append("(%s) Tj" % _escape_pdf_text(line.text))
        content_lines.append("T*")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R"
        + (b" /F2 6 0 R" if bold_used else b"")
        + b" >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    if bold_used:
        objects.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: List[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % number).encode("ascii") + body + b"\nendobj\n"

    xref_offset = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += ("%010d 00000 n \n" % offset).encode("ascii")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref_offset)).encode("ascii")
    return bytes(out)


class DocumentMetadata(NamedTuple):
    """What the retention job needs to know about a document.

    Not the bytes: the job looks at thousands of documents and needs the
    moment each was created, not the PDF.
    """

    document_id: str
    medication_request_id: str
    created_at: datetime


@dataclass(frozen=True)
class PrescriptionDocument:
    """The downloadable document of a prescription."""

    document_id: str
    medication_request_id: str
    content_type: str
    body: bytes
    checksum: str
    created_at: datetime

    @property
    def size(self) -> int:
        return len(self.body)

    def checksum_matches(self) -> bool:
        """Whether the stored bytes still hash to the recorded checksum."""
        import hashlib
        return hashlib.sha256(self.body).hexdigest() == self.checksum


class DocumentStore:
    """Stores prescription documents and their checksums.

    In production this is the encrypted object storage the architecture
    mentions; the metadata belongs in the ``prescription_document`` table
    (``db/prescription_schema.sql``). The bytes are kept in memory here.
    """

    def __init__(self):
        self._documents: Dict[str, PrescriptionDocument] = {}
        self._by_request: Dict[str, str] = {}

    def put(self, document: PrescriptionDocument) -> PrescriptionDocument:
        self._documents[document.document_id] = document
        self._by_request[document.medication_request_id] = document.document_id
        return document

    def get(self, document_id: str) -> Optional[PrescriptionDocument]:
        return self._documents.get(document_id)

    def get_for_request(self, medication_request_id: str) -> Optional[PrescriptionDocument]:
        document_id = self._by_request.get(medication_request_id)
        return self._documents.get(document_id) if document_id else None

    def all_metadata(self) -> List[DocumentMetadata]:
        """Every document, without its bytes.

        The retention job needs to see them all, to find the ones that are
        past their period.
        """
        return [DocumentMetadata(document.document_id,
                                 document.medication_request_id,
                                 document.created_at)
                for document in self._documents.values()]

    def __len__(self) -> int:
        return len(self._documents)


def prescription_document_lines(prescription: Prescription, *, patient: Optional[PatientRecord],
                                practitioner: Optional[PractitionerRecord],
                                issued_at: datetime) -> List[Union[str, PdfLine]]:
    """The lines of the prescription document.

    The document states who prescribed what, to whom, and when, and it says
    plainly that it is a record of the prescription rather than the
    prescription itself.

    **The medicine is printed the way a pharmacy needs it** (ENG-016): the
    brand and the strength large and bold, the generic name in brackets
    under it, and the NAFDAC registration number under that. A prescription
    without a brand or without a registration number is not printed at all —
    a pharmacy cannot dispense it, and a document that looks like a
    prescription is worse than an error.
    """
    # The brand and the registration number are checked before anything is
    # drawn, so that a document is never half a prescription.
    validate_dispensing_identity(prescription.brand_name, prescription.nafdac_number)

    patient_name = patient.display_name if patient else "the patient"
    practitioner_name = practitioner.display_name if practitioner else "the clinician"
    identifier = practitioner.identifier if practitioner and practitioner.identifier else ""
    headline = (f"{prescription.brand_name} {prescription.strength}".strip()
                if prescription.strength else prescription.brand_name)
    return [
        "E-PRESCRIPTION",
        "",
        "Prescription id: %s" % prescription.prescription_id,
        "Issued: %s" % issued_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "Status: %s" % prescription.status,
        "",
        "Patient: %s" % patient_name,
        "Prescriber: %s%s" % (practitioner_name, f" ({identifier})" if identifier else ""),
        "",
        PdfLine(headline, size=16, bold=True, space_before=6),
        "[%s]" % prescription.generic_name,
        "NAFDAC REG NO: %s" % prescription.nafdac_number,
        "",
        "Directions: %s" % prescription.dosage_text,
        "",
        "Medication code: %s" % prescription.medication_code,
        "Catalogue: %s" % prescription.medication_system,
        "",
        "This document is the record of the prescription issued during the",
        "telemedicine consultation. It is not a substitute for the medication",
        "itself, and it is issued to the patient named above only.",
    ]


class PrescriptionService:
    """Issues, views, downloads and changes prescriptions."""

    def __init__(self, records: RecordsService, documents: Optional[DocumentStore] = None,
                 audit: Optional[AuditLog] = None, notifications=None, clock=_utc_now):
        self.records = records
        self.documents = documents if documents is not None else DocumentStore()
        self.audit = audit if audit is not None else records.audit
        # Optional: where the "your prescription is ready" message is queued.
        self.notifications = notifications
        self._clock = clock

    # -- issuing ----------------------------------------------------------

    def issue(self, actor: UserAccount, encounter_id: str, *, medication_code: str,
              medication_display: str, dosage_text: str,
              **details) -> Tuple[Prescription, PrescriptionDocument]:
        """Issue a prescription against an encounter and render its document.

        The authorization and the audit entry are the ones of ENG-002: only
        the clinician who treated the encounter may issue it, and the create
        is audited. The document is rendered and stored with its checksum.
        """
        prescription = self.records.issue_prescription(
            actor, encounter_id,
            medication_code=medication_code,
            medication_display=medication_display,
            dosage_text=dosage_text,
            authored_on=self._clock(),
            **details,
        )
        document = self._render_document(prescription)
        return prescription, document

    def _render_document(self, prescription: Prescription) -> PrescriptionDocument:
        import hashlib
        patient = self.records.patient_record(prescription.patient_id)
        practitioner = self.records.practitioner_record(prescription.prescriber_id)
        lines = prescription_document_lines(
            prescription, patient=patient, practitioner=practitioner,
            issued_at=prescription.authored_on or self._clock())
        body = render_pdf(lines)
        document = PrescriptionDocument(
            document_id=str(uuid.uuid4()),
            medication_request_id=prescription.prescription_id,
            content_type=CONTENT_TYPE_PDF,
            body=body,
            checksum=hashlib.sha256(body).hexdigest(),
            created_at=self._clock(),
        )
        self.documents.put(document)
        self._notify_prescription(prescription)
        self.audit.append(
            actor_user_id=None,
            actor_role="system",
            action=ACTION_DOCUMENT_RENDER,
            resource_type=ResourceType.MEDICATION_REQUEST.value,
            resource_id=prescription.prescription_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"rendered document {document.document_id} ({document.size} bytes)",
        )
        return document

    # -- viewing and downloading ------------------------------------------

    def _notify_prescription(self, prescription: Prescription) -> None:
        """Tell the patient that their prescription is ready.

        The message is queued rather than sent, for the same reason the
        booking's is: the delivery is somebody else's job.
        """
        if self.notifications is None:
            return
        from telemedicine.notifications import (
            AUDIENCE_PATIENT,
            KIND_PRESCRIPTION_ISSUED,
            prescription_message,
        )
        subject, body = prescription_message(prescription, AUDIENCE_PATIENT)
        self.notifications.queue(kind=KIND_PRESCRIPTION_ISSUED,
                                 recipient_user_id=prescription.patient_user_id,
                                 subject=subject, body=body)

    def read(self, actor: UserAccount, prescription_id: str) -> Prescription:
        """Read a prescription. Authorized and audited by ENG-002's service."""
        return self.records.read_prescription(actor, prescription_id)

    def download(self, actor: UserAccount, prescription_id: str) -> bytes:
        """Download the document of a prescription.

        The download is a read, so it goes through the same rule: the patient
        the prescription is for, or the clinician who issued it. The download
        itself is audited separately, because a document that leaves the
        system is worth knowing about.
        """
        prescription = self._read_for_download(actor, prescription_id)
        document = self.documents.get_for_request(prescription.prescription_id)
        if document is None:
            raise ValidationError(
                f"no document has been rendered for prescription {prescription_id}")
        if not document.checksum_matches():
            self.audit.append(
                actor_user_id=actor.user_id,
                actor_role=actor.role.value,
                action=ACTION_DOWNLOAD,
                resource_type=ResourceType.MEDICATION_REQUEST.value,
                resource_id=prescription_id,
                outcome=OUTCOME_ERROR,
                detail="the stored document does not match its checksum; download refused",
            )
            raise ValidationError("the stored document does not match its checksum")
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_DOWNLOAD,
            resource_type=ResourceType.MEDICATION_REQUEST.value,
            resource_id=prescription_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"downloaded document {document.document_id} ({document.size} bytes)",
        )
        return document.body

    def list_for_encounter(self, actor: UserAccount, encounter_id: str) -> List[Prescription]:
        return self.records.list_prescriptions_for_encounter(actor, encounter_id)

    def _read_for_download(self, actor: UserAccount, prescription_id: str) -> Prescription:
        """Read a prescription for a download, auditing a refusal as a download.

        The read itself is audited by the records service. A refused
        download needs its own entry as well, because a document that did
        not leave the system is exactly what an investigator wants to know.
        """
        try:
            return self.records.read_prescription(actor, prescription_id)
        except AuthorizationError as error:
            self.audit.append(
                actor_user_id=actor.user_id,
                actor_role=actor.role.value,
                action=ACTION_DOWNLOAD,
                resource_type=ResourceType.MEDICATION_REQUEST.value,
                resource_id=prescription_id,
                outcome=OUTCOME_DENIED,
                detail=f"download a prescription — denied: {error}",
            )
            raise

    # -- lifecycle --------------------------------------------------------

    def change_status(self, actor: UserAccount, prescription_id: str, status: str, *,
                      reason: str = "") -> Prescription:
        """Move a prescription to another status.

        Only the clinician who issued it may change it, and only along an
        allowed transition. A completed, cancelled or stopped prescription is
        final.
        """
        if status not in ALLOWED_STATUSES:
            raise ValidationError(f"'{status}' is not a prescription status")
        prescription = self.records.get_prescription(prescription_id)
        current = prescription.status
        if status not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            self.audit.append(
                actor_user_id=actor.user_id,
                actor_role=actor.role.value,
                action=ACTION_STATUS_CHANGE,
                resource_type=ResourceType.MEDICATION_REQUEST.value,
                resource_id=prescription_id,
                outcome=OUTCOME_DENIED,
                detail=f"denied: cannot change a prescription from {current} to {status}",
            )
            raise ValidationError(
                f"a prescription cannot move from '{current}' to '{status}'")
        if status == STATUS_CANCELLED and not reason:
            raise ValidationError("cancelling a prescription needs a reason")

        updated = self.records.update_prescription_status(actor, prescription_id, status,
                                                           reason=reason)
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_STATUS_CHANGE,
            resource_type=ResourceType.MEDICATION_REQUEST.value,
            resource_id=prescription_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"changed from {current} to {status}"
                   + (f": {reason}" if reason else ""),
        )
        return updated

    def complete(self, actor: UserAccount, prescription_id: str) -> Prescription:
        return self.change_status(actor, prescription_id, STATUS_COMPLETED)

    def cancel(self, actor: UserAccount, prescription_id: str, reason: str) -> Prescription:
        return self.change_status(actor, prescription_id, STATUS_CANCELLED, reason=reason)
