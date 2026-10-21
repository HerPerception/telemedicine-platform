"""The prescription documents, in the database.

A prescription document is the record of what was prescribed, and it is the
thing a patient prints and takes to a pharmacy. Two things follow from that:

* it has to survive a restart, like every other clinical record;
* it must not be quietly changed. The schema of ENG-005 refuses an
  ``UPDATE`` on the row, and this feature extends that to a ``DELETE`` —
  a document that could be removed would not be a record of anything.

The bytes are stored in the database here, in a ``bytea`` column. A
deployment would put them in the encrypted object store that the
architecture describes, behind the same interface; the difference between
the two is the storage, not the behaviour.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from telemedicine.persistence.database import Database
from telemedicine.prescriptions import PrescriptionDocument


class PostgresDocumentStore:
    """The prescription documents, in the ``prescription_document`` table."""

    def __init__(self, database: Database):
        self.database = database

    def put(self, document: PrescriptionDocument) -> PrescriptionDocument:
        """Store a document.

        A prescription has one document. A second one for the same
        prescription is refused, exactly as the unique constraint of the
        table refuses it — the document of a prescription is what it said
        when it was issued.
        """
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO prescription_document (id, medication_request_id, storage_key,"
                " content_type, checksum, byte_size, body, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (document.document_id, document.medication_request_id,
                 f"prescription_document/{document.document_id}",
                 document.content_type, document.checksum, document.size,
                 document.body, document.created_at))
        return document

    def get(self, document_id: str) -> Optional[PrescriptionDocument]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, medication_request_id, content_type, body, checksum, created_at"
                    " FROM prescription_document WHERE id = %s", (document_id,))
                row = cursor.fetchone()
        return _to_document(row) if row else None

    def get_for_request(self, medication_request_id: str) -> Optional[PrescriptionDocument]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, medication_request_id, content_type, body, checksum, created_at"
                    " FROM prescription_document WHERE medication_request_id = %s",
                    (medication_request_id,))
                row = cursor.fetchone()
        return _to_document(row) if row else None

    def all_metadata(self) -> list:
        """Every document, without its bytes.

        The retention job reads this to find the documents that are past
        their period; loading the PDFs of a whole practice to do that would
        be a waste of memory for no reason.
        """
        from telemedicine.prescriptions import DocumentMetadata
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, medication_request_id, created_at"
                    " FROM prescription_document ORDER BY created_at")
                return [DocumentMetadata(str(row[0]), str(row[1]), row[2])
                        for row in cursor.fetchall()]

    def verify_checksum(self, document_id: str) -> bool:
        """Whether the stored bytes still hash to the recorded checksum."""
        document = self.get(document_id)
        return document is not None and document.checksum_matches()

    def __len__(self) -> int:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM prescription_document")
                return int(cursor.fetchone()[0])


def _to_document(row) -> PrescriptionDocument:
    body = bytes(row[3])
    return PrescriptionDocument(
        document_id=str(row[0]),
        medication_request_id=str(row[1]),
        content_type=row[2],
        body=body,
        checksum=row[4],
        created_at=row[5],
    )


def checksum_of(body: bytes) -> str:
    """The checksum a document is stored with."""
    return hashlib.sha256(body).hexdigest()
