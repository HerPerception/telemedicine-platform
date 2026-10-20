"""Role-scoped authorization.

Two roles exist (see :class:`telemedicine.models.Role`): a patient and a
practitioner. The rules below decide what each may do with each clinical
resource, and — just as importantly — *whose* data they may touch.

Access is decided from an :class:`AccessScope`, which describes the record
being accessed: who owns it, which clinicians have a treatment relationship
with it, and (for a prescription) who issued it. The scope is assembled by the
service layer from the clinical data, so the authorizer never has to query
anything itself.

The rule table is deliberately small and explicit. A request that matches no
rule is denied: there is no implicit "allow" and no wildcard.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple

from telemedicine.errors import AuthorizationError
from telemedicine.models import Role, UserAccount


class Action(str, enum.Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


class ResourceType(str, enum.Enum):
    PATIENT = "patient"
    PRACTITIONER = "practitioner"
    APPOINTMENT = "appointment"
    ENCOUNTER = "encounter"
    MEDICATION_REQUEST = "medication_request"
    # Added by ENG-003 (appointment booking and schedule management): the
    # bookable windows in a practitioner's schedule.
    SLOT = "slot"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


# Scope kinds.
OWN = "own"                          # the actor owns the record
TREATING = "treating"                # the actor has a treatment relationship with it
TREATING_OR_ISSUER = "treating_or_issuer"  # either of the above


@dataclass(frozen=True)
class AccessScope:
    """Who the record belongs to, and who may act on it.

    ``owner_user_id``
        The user account of the patient (for patient records, appointments,
        encounters and prescriptions) or of the practitioner (for a
        practitioner record).
    ``treating_user_ids``
        The user accounts of clinicians who treat the subject of the record.
    ``issued_by_user_id``
        For a prescription, the clinician who issued it.
    """

    owner_user_id: Optional[str] = None
    treating_user_ids: FrozenSet[str] = field(default_factory=frozenset)
    issued_by_user_id: Optional[str] = None


@dataclass(frozen=True)
class Rule:
    role: Role
    resource_type: ResourceType
    action: Action
    scope: str
    description: str

    @property
    def key(self) -> str:
        return f"{self.role.value}:{self.resource_type.value}:{self.action.value}"


@dataclass(frozen=True)
class Decision:
    """The result of an authorization check."""

    allowed: bool
    reason: str
    rule: Optional[Rule] = None

    def __bool__(self) -> bool:
        return self.allowed


RULES: Tuple[Rule, ...] = (
    # A patient may read their own clinical data and nothing else.
    Rule(Role.PATIENT, ResourceType.PATIENT, Action.READ, OWN,
         "a patient may read their own patient record"),
    Rule(Role.PATIENT, ResourceType.APPOINTMENT, Action.READ, OWN,
         "a patient may read their own appointments"),
    Rule(Role.PATIENT, ResourceType.ENCOUNTER, Action.READ, OWN,
         "a patient may read their own encounters"),
    Rule(Role.PATIENT, ResourceType.MEDICATION_REQUEST, Action.READ, OWN,
         "a patient may read their own prescriptions"),

    # A practitioner may read their own practitioner record.
    Rule(Role.PRACTITIONER, ResourceType.PRACTITIONER, Action.READ, OWN,
         "a practitioner may read their own practitioner record"),

    # A practitioner may read the record of a patient they treat, and the
    # appointments and encounters that make up that treatment relationship.
    Rule(Role.PRACTITIONER, ResourceType.PATIENT, Action.READ, TREATING,
         "a practitioner may read the record of a patient they treat"),
    Rule(Role.PRACTITIONER, ResourceType.APPOINTMENT, Action.READ, TREATING,
         "a practitioner may read the appointments of a patient they treat"),
    Rule(Role.PRACTITIONER, ResourceType.ENCOUNTER, Action.READ, TREATING,
         "a practitioner may read the encounters of a patient they treat"),
    Rule(Role.PRACTITIONER, ResourceType.ENCOUNTER, Action.CREATE, TREATING,
         "a practitioner may record an encounter for a patient they treat"),

    # Prescriptions are readable by the patient and by the clinician who
    # issued them, and may only be issued by the treating clinician.
    Rule(Role.PRACTITIONER, ResourceType.MEDICATION_REQUEST, Action.READ, TREATING_OR_ISSUER,
         "a practitioner may read prescriptions they issued or that concern a patient they treat"),
    Rule(Role.PRACTITIONER, ResourceType.MEDICATION_REQUEST, Action.CREATE, TREATING,
         "only the treating clinician may issue a prescription"),

    # --- ENG-005: the prescription lifecycle -----------------------------
    # A prescription is changed by the clinician who issued it. A patient may
    # read and download their own prescriptions, but may not change one.
    Rule(Role.PRACTITIONER, ResourceType.MEDICATION_REQUEST, Action.UPDATE, TREATING,
         "the treating clinician may change a prescription they issued"),

    # --- ENG-003: booking and schedule management ------------------------
    # A patient books, reschedules and cancels their own appointments; a
    # practitioner does the same for the patients they treat, and manages the
    # slots of their own schedule.
    Rule(Role.PATIENT, ResourceType.APPOINTMENT, Action.CREATE, OWN,
         "a patient may book an appointment for themselves"),
    Rule(Role.PATIENT, ResourceType.APPOINTMENT, Action.UPDATE, OWN,
         "a patient may reschedule or cancel their own appointment"),
    Rule(Role.PRACTITIONER, ResourceType.APPOINTMENT, Action.CREATE, TREATING,
         "a practitioner may book an appointment in their own schedule for a patient they treat"),
    Rule(Role.PRACTITIONER, ResourceType.APPOINTMENT, Action.UPDATE, TREATING,
         "a practitioner may reschedule or cancel appointments they deliver"),
    Rule(Role.PRACTITIONER, ResourceType.SLOT, Action.CREATE, OWN,
         "a practitioner may open slots in their own schedule"),
    Rule(Role.PRACTITIONER, ResourceType.SLOT, Action.UPDATE, OWN,
         "a practitioner may close or change slots in their own schedule"),
)


class Authorizer:
    """Decides whether an actor may perform an action on a resource."""

    def __init__(self, rules: Tuple[Rule, ...] = RULES):
        self._rules: Dict[Tuple[Role, ResourceType, Action], Rule] = {
            (rule.role, rule.resource_type, rule.action): rule for rule in rules
        }

    @property
    def rules(self) -> Tuple[Rule, ...]:
        return tuple(self._rules.values())

    def decide(self, actor: UserAccount, action: Action, resource_type: ResourceType,
               scope: AccessScope) -> Decision:
        """Return the decision for one access attempt.

        The actor must be active: a disabled account is refused every
        resource, whatever the rule table says.
        """
        if not actor.is_active:
            return Decision(False, "the account is disabled")

        rule = self._rules.get((actor.role, resource_type, action))
        if rule is None:
            return Decision(
                False,
                f"role '{actor.role.value}' may not {action.value} a {resource_type.value}",
            )

        if not self._scope_matches(rule.scope, actor, scope):
            return Decision(
                False,
                f"the {actor.role.value} account is not in scope for this "
                f"{resource_type.value} ({rule.scope} required)",
                rule,
            )
        return Decision(True, rule.description, rule)

    def require(self, actor: UserAccount, action: Action, resource_type: ResourceType,
                scope: AccessScope, *, resource_id: str = "") -> None:
        """Raise :class:`AuthorizationError` unless the access is allowed."""
        decision = self.decide(actor, action, resource_type, scope)
        if not decision.allowed:
            raise AuthorizationError(
                decision.reason,
                resource_type=resource_type.value,
                resource_id=resource_id,
                action=action.value,
            )

    @staticmethod
    def _scope_matches(scope_kind: str, actor: UserAccount, scope: AccessScope) -> bool:
        if scope_kind == OWN:
            return scope.owner_user_id is not None and scope.owner_user_id == actor.user_id
        if scope_kind == TREATING:
            return actor.user_id in scope.treating_user_ids
        if scope_kind == TREATING_OR_ISSUER:
            return (actor.user_id in scope.treating_user_ids
                    or (scope.issued_by_user_id is not None
                        and scope.issued_by_user_id == actor.user_id))
        raise ValueError(f"unknown scope kind '{scope_kind}'")
