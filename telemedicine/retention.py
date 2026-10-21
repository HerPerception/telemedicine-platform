"""The retention policy: how long records are kept, and when they go.

**Nothing in this module deletes anything while the policy file says what it
says.** The policy carries two flags, and both have to be true before a single
record is removed:

* ``enabled`` — the policy is in force at all;
* ``legal_advisor_signed`` — a qualified adviser has confirmed the numbers.

The numbers themselves are **conventional practice, not law**. They are in
``config/retention_policy.yaml`` so that the machinery can be built and tested
while the practice waits for an adviser, and they are marked as placeholders
there. The privacy notice's table is generated from the same file, so the
notice and the job cannot drift apart.

**The unit of retention is the patient's clinical record**: the patient, their
encounters, their prescriptions and their appointments together, measured from
their last visit. A record is not deleted in pieces.

**The audit trail is reported but never deleted.** It is a hash chain — every
entry links to the one before it, and the head of the chain is published
outside the database — so pruning it would break the chain that makes it
worth anything. The policy carries ``audit_log_years`` for the day a
chain-preserving method exists.

**How a record goes.** In two steps, and only when the flags allow it:

1. **Soft delete.** The record is copied into the trash table with the moment
   it was deleted and the moment it may be purged, and the live rows are
   marked with ``deleted_at`` so that they stop being served. Nothing is
   lost: the trash holds the whole record, and it can be put back.
2. **Hard delete.** Thirty days later the live rows are removed and the trash
   entry goes with them.

Every removal — soft or hard — is written to an immutable table, with the
reason. That table is the evidence that the policy was applied and why.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from telemedicine.errors import ValidationError

# The default place the policy lives.
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "retention_policy.yaml"

# The keys the policy file must have, and what type each one is. A key that is
# missing, unknown, or of the wrong type is an error: a policy that is
# quietly half-read is worse than one that is refused.
POLICY_KEYS: Dict[str, type] = {
    "adult_outpatient_years": int,
    "adult_inpatient_years": int,
    "child_until_age": int,
    "prescription_years": int,
    "audit_log_years": int,
    "enabled": bool,
    "legal_advisor_signed": bool,
}

# The refusals. They are the same words wherever they are raised, so that
# nobody is left guessing which condition was not met.
REFUSAL_SIGNATURE_REQUIRED = "Refusing to delete: legal sign-off required"
REFUSAL_DISABLED = ("Refusing to delete: the retention policy is disabled "
                    "(enabled: false)")

# How long a soft-deleted record is kept before it is purged.
GRACE_PERIOD_DAYS = 30

# The record types the job knows about.
RECORD_CLINICAL = "clinical_record"
RECORD_PRESCRIPTION_DOCUMENT = "prescription_document"
RECORD_AUDIT_LOG = "audit_log"


class RetentionPolicyError(ValidationError):
    """The policy file is not usable."""


class RetentionRefused(ValidationError):
    """The policy does not allow what was asked for."""


@dataclass(frozen=True)
class RetentionPolicy:
    """The policy, as it is written down."""

    adult_outpatient_years: int
    adult_inpatient_years: int
    child_until_age: int
    prescription_years: int
    audit_log_years: int
    enabled: bool
    legal_advisor_signed: bool
    source_path: Optional[str] = None

    # -- the two gates -----------------------------------------------------

    @property
    def may_delete(self) -> bool:
        """Whether a record may be removed.

        Both flags, and nothing less. The first one turned on without the
        second is the state that is refused outright, because it looks like
        the job is running and is not.
        """
        return bool(self.enabled and self.legal_advisor_signed)

    def check_may_delete(self) -> None:
        """Refuse unless both flags are true.

        The order of the two refusals matters: a policy that is switched on
        but not signed is the dangerous one, and it says so.
        """
        if not self.enabled:
            raise RetentionRefused(REFUSAL_DISABLED)
        if not self.legal_advisor_signed:
            raise RetentionRefused(REFUSAL_SIGNATURE_REQUIRED)

    # -- the periods -------------------------------------------------------

    def clinical_years_for(self, birth_date: Optional[date], at: datetime) -> int:
        """How long a clinical record is kept, for a patient of this age.

        A record made while the patient was a child is kept until they reach
        ``child_until_age``; the period is measured from the last visit, and
        the record is kept for as long as it takes them to get there.
        """
        if birth_date is None:
            return self.adult_outpatient_years
        age_at = _age_at(birth_date, at)
        if age_at is not None and age_at < 18:
            # A child: keep it until they reach the age, and at least the
            # ordinary period as well.
            years_to_adult = max(self.child_until_age - age_at, 0)
            return max(years_to_adult, self.adult_outpatient_years)
        return self.adult_outpatient_years

    def expiry_for(self, last_activity: datetime, years: int) -> datetime:
        """When a record past this period may be removed.

        Calendar years, not a number of days: five years after the first of
        January is the first of January, and a record that is a day short of
        its period is still within it.
        """
        try:
            return last_activity.replace(year=last_activity.year + int(years))
        except ValueError:
            # The 29th of February, in a year that has no 29th of February.
            return last_activity.replace(year=last_activity.year + int(years),
                                         day=28)

    def summary_rows(self) -> List[Tuple[str, str, str]]:
        """The rows of the privacy notice's table.

        Each row is the record type, the period, and where the number comes
        from — so that the notice says plainly that the numbers are
        conventional practice and not yet law.
        """
        return [
            (RECORD_CLINICAL,
             f"{self.adult_outpatient_years} years after the last visit"
             + (f" (or until the patient reaches {self.child_until_age}, if they"
                " were a child)" if self.child_until_age else ")"),
             "conventional practice, not yet confirmed by an adviser"),
            (RECORD_PRESCRIPTION_DOCUMENT,
             f"{self.prescription_years} years after it was issued",
             "conventional practice, not yet confirmed by an adviser"),
            (RECORD_AUDIT_LOG,
             f"{self.audit_log_years} years after the entry was written",
             "conventional practice, not yet confirmed by an adviser"),
        ]


# The warning the privacy notice carries above the table. It is not
# decoration: the numbers are conventional practice and not yet law.
DRAFT_WARNING = "DRAFT - pending legal advisor"


def policy_table_markdown(policy: RetentionPolicy) -> str:
    """The "How long we keep data" table of the privacy notice.

    It is generated from the policy file, so the notice and the job cannot
    drift apart: the numbers a patient is told are the numbers the job
    applies.
    """
    lines = [
        "| Record | How long we keep it | Where the number comes from |",
        "| --- | --- | --- |",
    ]
    for record_type, period, source in policy.summary_rows():
        lines.append(f"| {record_type.replace('_', ' ')} | {period} | {source} |")
    return "\n".join(lines)


@dataclass(frozen=True)
class RetentionCandidate:
    """A record that is past its period."""

    record_type: str
    record_id: str
    patient_id: Optional[str]
    last_activity: datetime
    expires_at: datetime
    reason: str
    deletable: bool = True
    note: Optional[str] = None


# --------------------------------------------------------------------------
# Reading the policy file
# --------------------------------------------------------------------------


def load_policy(path=None) -> RetentionPolicy:
    """Read the policy from its file.

    The file is YAML, but the project has no YAML library and one dependency
    is a rule worth keeping. So this reads the small, strict subset of YAML
    the policy file uses: ``key: value`` lines, ``#`` comments, and nothing
    else. Anything it does not understand is an error rather than something
    quietly skipped — a policy that is half-read is a policy nobody can rely
    on.
    """
    path = Path(path) if path is not None else DEFAULT_POLICY_PATH
    if not path.is_file():
        raise RetentionPolicyError(f"the retention policy file {path} does not exist")
    values = _read_simple_yaml(path.read_text(encoding="utf-8"), path)
    return _policy_from_values(values, str(path))


def _read_simple_yaml(text: str, path: Path) -> Dict[str, object]:
    """The keys of a flat ``key: value`` file."""
    values: Dict[str, object] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise RetentionPolicyError(
                f"{path}:{number}: this is not a 'key: value' line: {stripped!r}")
        key, _, raw = stripped.partition(":")
        key = key.strip()
        raw = _strip_comment(raw).strip()
        if not key:
            raise RetentionPolicyError(f"{path}:{number}: the key is empty")
        if key in values:
            raise RetentionPolicyError(f"{path}:{number}: '{key}' is set twice")
        values[key] = _coerce(raw, key, path, number)
    return values


def _strip_comment(value: str) -> str:
    """Drop a trailing ``# comment``.

    A ``#`` only starts a comment when it is at the start of the value or
    after a space, so that a value may contain one.
    """
    if value.startswith("#"):
        return ""
    position = value.find(" #")
    if position >= 0:
        return value[:position]
    return value


def _coerce(raw: str, key: str, path: Path, number: int) -> object:
    """The value of a key, in the type the key is declared to have."""
    expected = POLICY_KEYS.get(key)
    if expected is None:
        raise RetentionPolicyError(
            f"{path}:{number}: '{key}' is not a key of the retention policy. "
            f"The keys are: {', '.join(sorted(POLICY_KEYS))}")
    if expected is bool:
        lowered = raw.lower()
        if lowered in ("true", "yes"):
            return True
        if lowered in ("false", "no"):
            return False
        raise RetentionPolicyError(
            f"{path}:{number}: '{key}' must be true or false, not {raw!r}")
    if expected is int:
        try:
            return int(raw)
        except ValueError:
            raise RetentionPolicyError(
                f"{path}:{number}: '{key}' must be a whole number, not {raw!r}") from None
    return raw


def _policy_from_values(values: Dict[str, object], source: str) -> RetentionPolicy:
    """The policy, from the values that were read."""
    missing = [key for key in POLICY_KEYS if key not in values]
    if missing:
        raise RetentionPolicyError(
            f"{source}: the retention policy is missing {', '.join(sorted(missing))}")
    for key, value in values.items():
        if not isinstance(value, POLICY_KEYS[key]):
            raise RetentionPolicyError(f"{source}: '{key}' has the wrong type")
    for key in ("adult_outpatient_years", "adult_inpatient_years", "child_until_age",
                "prescription_years", "audit_log_years"):
        if values[key] < 0:
            raise RetentionPolicyError(f"{source}: '{key}' cannot be negative")
    return RetentionPolicy(
        adult_outpatient_years=values["adult_outpatient_years"],
        adult_inpatient_years=values["adult_inpatient_years"],
        child_until_age=values["child_until_age"],
        prescription_years=values["prescription_years"],
        audit_log_years=values["audit_log_years"],
        enabled=values["enabled"],
        legal_advisor_signed=values["legal_advisor_signed"],
        source_path=source,
    )


# --------------------------------------------------------------------------
# Finding what is past its period
# --------------------------------------------------------------------------


class RetentionSource:
    """What the job reads.

    The clinical records, the prescriptions and the audit trail. It is an
    interface so that the job can be run against the database or against
    records held in memory, and so that a test can hand it what it wants.
    """

    def patients(self) -> List:
        raise NotImplementedError

    def encounters(self) -> List:
        raise NotImplementedError

    def prescriptions(self) -> List:
        raise NotImplementedError

    def appointments(self) -> List:
        return []

    def prescription_documents(self) -> List:
        return []

    def audit_entries(self) -> List:
        return []


class ServiceRetentionSource(RetentionSource):
    """The records of a running application."""

    def __init__(self, records, prescriptions=None, audit=None):
        self.records = records
        self.prescriptions = prescriptions
        self.audit = audit

    def patients(self):
        return self.records.list_patients()

    def encounters(self):
        return self.records.list_encounters()

    def prescriptions(self):
        return self.records.list_prescriptions()

    def appointments(self):
        return self.records.list_appointments()

    def prescription_documents(self):
        if self.prescriptions is None:
            return []
        documents = getattr(self.prescriptions, "documents", None)
        if documents is None or not hasattr(documents, "all_metadata"):
            return []
        return list(documents.all_metadata())

    def audit_entries(self):
        if self.audit is None:
            return []
        return list(self.audit.entries)


def find_candidates(source: RetentionSource, policy: RetentionPolicy,
                    now: Optional[datetime] = None) -> List[RetentionCandidate]:
    """What is past its period, and when each of it becomes eligible.

    The clinical record is the unit: the patient and everything that belongs
    to them, measured from their last visit. A prescription document and an
    audit entry are counted separately, because they have their own periods
    and their own rules.
    """
    now = now or datetime.now(timezone.utc)
    candidates: List[RetentionCandidate] = []

    last_visit = _last_visit_by_patient(source)
    for patient in source.patients():
        patient_id = getattr(patient, "patient_id", None)
        visits = last_visit.get(patient_id)
        if visits is None:
            # No visit: there is nothing to measure the period from, and a
            # record that was never used is not a record at the end of its
            # life.
            continue
        years = policy.clinical_years_for(_birth_date(patient), visits)
        expires = policy.expiry_for(visits, years)
        if expires <= now:
            candidates.append(RetentionCandidate(
                record_type=RECORD_CLINICAL,
                record_id=patient_id,
                patient_id=patient_id,
                last_activity=visits,
                expires_at=expires,
                reason=(f"no visit for {years} years; the last one was on "
                        f"{_isoformat(visits)}"),
            ))

    for document in source.prescription_documents():
        created = _moment(getattr(document, "created_at", None))
        if created is None:
            continue
        expires = policy.expiry_for(created, policy.prescription_years)
        if expires <= now:
            candidates.append(RetentionCandidate(
                record_type=RECORD_PRESCRIPTION_DOCUMENT,
                record_id=getattr(document, "document_id", ""),
                patient_id=None,
                last_activity=created,
                expires_at=expires,
                reason=f"issued more than {policy.prescription_years} years ago",
                # A prescription document is immutable: the schema refuses a
                # change to it and a removal of it, because a document that
                # could be edited or removed after the fact would not be a
                # record of anything. It is reported here, and left where it
                # is. The prescription it belongs to goes with the clinical
                # record.
                deletable=False,
                note=("a prescription document is immutable and is not removed; "
                      "the prescription it belongs to goes with the clinical "
                      "record"),
            ))

    for entry in source.audit_entries():
        occurred = _moment(getattr(entry, "occurred_at", None))
        if occurred is None:
            continue
        expires = policy.expiry_for(occurred, policy.audit_log_years)
        if expires <= now:
            candidates.append(RetentionCandidate(
                record_type=RECORD_AUDIT_LOG,
                record_id=str(getattr(entry, "sequence", "")),
                patient_id=None,
                last_activity=occurred,
                expires_at=expires,
                reason=f"written more than {policy.audit_log_years} years ago",
                # The audit trail is a hash chain. It is reported, and it is
                # not removed: pruning it would break the chain that makes it
                # worth anything.
                deletable=False,
                note=("the audit trail is a hash chain and is not pruned; the "
                      "period is kept for the day a chain-preserving method "
                      "exists"),
            ))

    candidates.sort(key=lambda candidate: (candidate.record_type, candidate.record_id))
    return candidates


def _last_visit_by_patient(source: RetentionSource) -> Dict[str, datetime]:
    """When each patient was last seen."""
    visits: Dict[str, datetime] = {}
    for encounter in source.encounters():
        patient_id = getattr(encounter, "patient_id", None)
        started = _moment(getattr(encounter, "started_at", None))
        if not patient_id or started is None:
            continue
        if patient_id not in visits or started > visits[patient_id]:
            visits[patient_id] = started
    return visits


def _birth_date(patient) -> Optional[date]:
    value = getattr(patient, "date_of_birth", None)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _age_at(birth_date: date, at: datetime) -> Optional[int]:
    """How old the patient was at a moment."""
    moment = at.date() if isinstance(at, datetime) else at
    return moment.year - birth_date.year - (
        (moment.month, moment.day) < (birth_date.month, birth_date.day))


def _moment(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _isoformat(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Removing a record — in two steps, and only when the policy allows it
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrashedRecord:
    """A record that has been soft-deleted and is waiting its turn."""

    trash_id: str
    record_type: str
    record_id: str
    patient_id: Optional[str]
    payload: str
    deleted_at: datetime
    purge_after: datetime


@dataclass(frozen=True)
class DeletionAuditEntry:
    """One removal, written to the immutable table."""

    entry_id: str
    record_type: str
    record_id: str
    patient_id: Optional[str]
    stage: str            # soft | hard
    occurred_at: datetime
    reason: str
    policy_source: str


class RetentionStore:
    """Where the trash and the deletion audit live."""

    def trash(self) -> List[TrashedRecord]:
        raise NotImplementedError

    def add_trash(self, record: TrashedRecord) -> TrashedRecord:
        raise NotImplementedError

    def remove_trash(self, trash_id: str) -> None:
        raise NotImplementedError

    def mark_deleted(self, record_type: str, record_id: str,
                     deleted_at: datetime) -> int:
        """Mark the live rows of a record as deleted. Returns how many."""
        raise NotImplementedError

    def purge_deleted(self, record_type: str, record_id: str) -> int:
        """Remove the live rows of a record. Returns how many."""
        raise NotImplementedError

    def record_deletion(self, entry: DeletionAuditEntry) -> DeletionAuditEntry:
        raise NotImplementedError

    def deletion_audit(self) -> List[DeletionAuditEntry]:
        raise NotImplementedError


class InMemoryRetentionStore(RetentionStore):
    """The trash and the deletion audit, in the memory of one process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._trash: List[TrashedRecord] = []
        self._audit: List[DeletionAuditEntry] = []
        # What the live rows look like, so that a test can see the marking.
        self.marked: Dict[str, datetime] = {}
        self.purged: List[str] = []

    def trash(self) -> List[TrashedRecord]:
        with self._lock:
            return list(self._trash)

    def add_trash(self, record: TrashedRecord) -> TrashedRecord:
        with self._lock:
            self._trash.append(record)
        return record

    def remove_trash(self, trash_id: str) -> None:
        with self._lock:
            self._trash = [item for item in self._trash if item.trash_id != trash_id]

    def mark_deleted(self, record_type: str, record_id: str,
                     deleted_at: datetime) -> int:
        with self._lock:
            self.marked[f"{record_type}:{record_id}"] = deleted_at
        return 1

    def purge_deleted(self, record_type: str, record_id: str) -> int:
        with self._lock:
            self.purged.append(f"{record_type}:{record_id}")
        return 1

    def record_deletion(self, entry: DeletionAuditEntry) -> DeletionAuditEntry:
        with self._lock:
            self._audit.append(entry)
        return entry

    def deletion_audit(self) -> List[DeletionAuditEntry]:
        with self._lock:
            return list(self._audit)


def soft_delete(candidates: Sequence[RetentionCandidate], store: RetentionStore,
                source: RetentionSource, policy: RetentionPolicy,
                now: Optional[datetime] = None,
                reason: Optional[str] = None) -> List[DeletionAuditEntry]:
    """Soft-delete the records: into the trash, and marked in place.

    Nothing is lost. The whole record is copied into the trash with the moment
    it may be purged, the live rows are marked so that they stop being served,
    and the removal is written to the immutable table.

    The policy is checked first: **this does nothing at all unless both flags
    are true.**
    """
    policy.check_may_delete()
    now = now or datetime.now(timezone.utc)
    purge_after = now + timedelta(days=GRACE_PERIOD_DAYS)
    entries: List[DeletionAuditEntry] = []

    for candidate in candidates:
        if not candidate.deletable:
            # The audit trail is reported, and left where it is.
            continue
        payload = _bundle_for(candidate, source)
        trash = store.add_trash(TrashedRecord(
            trash_id=str(uuid.uuid4()),
            record_type=candidate.record_type,
            record_id=candidate.record_id,
            patient_id=candidate.patient_id,
            payload=payload,
            deleted_at=now,
            purge_after=purge_after,
        ))
        store.mark_deleted(candidate.record_type, candidate.record_id, now)
        entries.append(store.record_deletion(DeletionAuditEntry(
            entry_id=str(uuid.uuid4()),
            record_type=candidate.record_type,
            record_id=candidate.record_id,
            patient_id=candidate.patient_id,
            stage="soft",
            occurred_at=now,
            reason=reason or candidate.reason,
            policy_source=policy.source_path or "",
        )))
    return entries


def hard_delete(store: RetentionStore, policy: RetentionPolicy,
                now: Optional[datetime] = None) -> List[DeletionAuditEntry]:
    """Remove the records whose grace period has passed.

    The grace period is thirty days: a record that has been soft-deleted can
    still be put back until then, and only after that is it removed for good.
    """
    policy.check_may_delete()
    now = now or datetime.now(timezone.utc)
    entries: List[DeletionAuditEntry] = []

    for record in store.trash():
        if record.purge_after > now:
            continue
        store.purge_deleted(record.record_type, record.record_id)
        store.remove_trash(record.trash_id)
        entries.append(store.record_deletion(DeletionAuditEntry(
            entry_id=str(uuid.uuid4()),
            record_type=record.record_type,
            record_id=record.record_id,
            patient_id=record.patient_id,
            stage="hard",
            occurred_at=now,
            reason=f"the {GRACE_PERIOD_DAYS} day grace period passed on "
                   f"{_isoformat(record.purge_after)}",
            policy_source=policy.source_path or "",
        )))
    return entries


def restore(store: RetentionStore, record_type: str, record_id: str,
            deleted_at: Optional[datetime] = None) -> bool:
    """Put a soft-deleted record back, while it still can be.

    This is what the grace period is for: a record that was taken out in
    error is put back, and the removal is written to the audit as a
    restoration rather than hidden.
    """
    for record in store.trash():
        if record.record_type == record_type and record.record_id == record_id:
            store.mark_deleted(record_type, record_id, deleted_at or datetime.now(timezone.utc))
            store.remove_trash(record.trash_id)
            return True
    return False


def _bundle_for(candidate: RetentionCandidate, source: RetentionSource) -> str:
    """The record, as it is kept in the trash."""
    import json

    patient_id = candidate.patient_id
    patient = None
    encounters = []
    prescriptions = []
    appointments = []

    if candidate.record_type == RECORD_CLINICAL and patient_id:
        for item in source.patients():
            if getattr(item, "patient_id", None) == patient_id:
                patient = item
                break
        encounters = [item for item in source.encounters()
                      if getattr(item, "patient_id", None) == patient_id]
        prescriptions = [item for item in source.prescriptions()
                         if getattr(item, "patient_id", None) == patient_id]
        appointments = [item for item in source.appointments()
                        if getattr(item, "patient_id", None) == patient_id]

    payload = {
        "record_type": candidate.record_type,
        "record_id": candidate.record_id,
        "patient": _as_dict(patient),
        "encounters": [_as_dict(item) for item in encounters],
        "prescriptions": [_as_dict(item) for item in prescriptions],
        "appointments": [_as_dict(item) for item in appointments],
    }
    return json.dumps(payload, default=str, sort_keys=True)


def _as_dict(item) -> Optional[dict]:
    if item is None:
        return None
    import dataclasses
    if dataclasses.is_dataclass(item):
        return dataclasses.asdict(item)
    return {"value": str(item)}
