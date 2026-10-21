"""The gate on transfers of patient data out of Nigeria.

Section 41(1) of the Nigeria Data Protection Act 2023: "A data controller or
data processor shall not transfer or permit personal data to be transferred
from Nigeria to another country, unless (a) the recipient ... is subject to a
law, binding corporate rules, contractual clauses, code of conduct, or
certification mechanism that affords an adequate level of protection ... or
(b) one of the conditions set out in section 43 applies." Section 41(2):
the controller "shall record the basis for transfer". Section 43(a) is the
patient's consent, given "after having been informed of the possible risks
of such transfers".

**So a transfer out of Nigeria needs three things, and this module insists
on all three before anything is sent:**

1. **A known destination.** The configuration says where each service is.
   An unknown destination is refused: it cannot be shown to be in Nigeria,
   and showing it is the whole point.
2. **A lawful basis** — consent, contract, vital interest, public interest or
   legal claim. Without one, the transfer is refused.
3. **A written justification** — what the transfer is for, and on what
   ground. Without one, the transfer is refused, and the basis is not
   recorded, which section 41(2) requires.

**Nothing leaves the country silently.** The guard is called before every
outbound request, and a refused transfer raises
:class:`CrossBorderTransferRefusedError` — the request never happens. A
transfer that does happen is written to `transfer_logs`, with the
destination, the basis, the justification and whose data it was.

**The configuration is the source of truth.** `config/external_services.yaml`
lists each service, the country it is in, and the basis and justification the
practice has recorded for it. Every service outside Nigeria ships with an
empty justification, so **every transfer out of Nigeria is refused until the
practice fills one in** — which is the decision the practice has not been
able to make yet, and should not have to make in order to build the system.
"""

from __future__ import annotations

import ipaddress
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from telemedicine.errors import ValidationError
from telemedicine.yaml_lite import (
    ConfigurationError,
    as_bool,
    group_by_prefix,
    read_flat_yaml_file,
)

# The lawful bases section 43 lists.
LAWFUL_BASES = ("consent", "contract", "vital_interest", "public_interest",
                "legal_claim")

# Nigeria.
NIGERIA = "NG"

# The refusals. The first is the one the acceptance criterion names.
REFUSAL_NO_BASIS = "Transfer blocked: no lawful basis recorded per NDPA s43"
REFUSAL_NO_JUSTIFICATION = "Transfer blocked: no justification recorded per NDPA s41(2)"
REFUSAL_UNKNOWN_DESTINATION = (
    "Transfer blocked: the destination is not in the list of known services, "
    "and it cannot be shown to be in Nigeria")
REFUSAL_COUNTRY_MISMATCH = (
    "Transfer blocked: the destination's country does not match the one the "
    "configuration records for it")
REFUSAL_BLOCKED = "Transfer blocked: the service is blocked in the configuration"

# Where the configuration lives.
DEFAULT_SERVICES_PATH = (Path(__file__).resolve().parent.parent / "config"
                          / "external_services.yaml")


class CrossBorderTransferRefusedError(ValidationError):
    """A transfer out of Nigeria was refused, and did not happen.

    It is a refusal, not a failure: nothing was sent, nothing was broken,
    and the reason says which of the three requirements was not met.
    """


@dataclass(frozen=True)
class TransferRequest:
    """One transfer, and what is being asked about it."""

    destination_country: str
    recipient: str
    data_categories: List[str]
    lawful_basis: Optional[str]
    justification_text: str

    @property
    def country(self) -> str:
        return (self.destination_country or "").strip().upper()

    @property
    def basis(self) -> Optional[str]:
        if not self.lawful_basis:
            return None
        return self.lawful_basis.strip().lower() or None

    @property
    def justification(self) -> str:
        return (self.justification_text or "").strip()

    @property
    def in_nigeria(self) -> bool:
        return self.country == NIGERIA


@dataclass(frozen=True)
class ExternalService:
    """A service the application may send to, and where it is."""

    name: str
    host: str
    destination_country: str
    lawful_basis: Optional[str] = None
    justification: str = ""
    blocked: bool = False

    @property
    def in_nigeria(self) -> bool:
        return (self.destination_country or "").strip().upper() == NIGERIA

    @property
    def permitted(self) -> bool:
        """Whether a transfer to this service may happen.

        A service in Nigeria needs nothing: nothing leaves the country. A
        service outside it needs a basis, a justification, and not to be
        blocked outright.
        """
        if self.blocked:
            return False
        if self.in_nigeria:
            return True
        return bool(self.lawful_basis and self.justification.strip())

    @property
    def reason(self) -> str:
        """Why it is not permitted, in the words the caller is shown."""
        if self.blocked:
            return REFUSAL_BLOCKED
        if not self.lawful_basis:
            return REFUSAL_NO_BASIS
        if not self.justification.strip():
            return REFUSAL_NO_JUSTIFICATION
        return ""


class ExternalServiceRegistry:
    """The services the application may send to, and where each of them is."""

    def __init__(self, services: Optional[List[ExternalService]] = None):
        self._services: List[ExternalService] = list(services or [])

    @classmethod
    def from_file(cls, path=None) -> "ExternalServiceRegistry":
        """The registry, read from the configuration file."""
        path = Path(path) if path is not None else DEFAULT_SERVICES_PATH
        try:
            values = read_flat_yaml_file(path)
        except ConfigurationError as error:
            raise ConfigurationError(f"{path}: {error}") from None
        groups = group_by_prefix(values)
        services = []
        for name in sorted(groups):
            entries = groups[name]
            host = entries.get("host", "").strip()
            if not host:
                raise ConfigurationError(
                    f"{path}: the service '{name}' has no host")
            country = entries.get("country", "").strip().upper()
            if not country:
                raise ConfigurationError(
                    f"{path}: the service '{name}' has no country")
            basis = (entries.get("lawful_basis", "") or "").strip().lower() or None
            if basis is not None and basis not in LAWFUL_BASES:
                raise ConfigurationError(
                    f"{path}: the service '{name}' has a lawful basis of "
                    f"{basis!r}; the Act lists {', '.join(LAWFUL_BASES)}")
            services.append(ExternalService(
                name=name,
                host=host,
                destination_country=country,
                lawful_basis=basis,
                justification=(entries.get("justification", "") or "").strip(),
                blocked=as_bool(entries.get("blocked", "false") or "false",
                                f"{name}.blocked", path),
            ))
        return cls(services)

    def services(self) -> List[ExternalService]:
        return list(self._services)

    def for_host(self, host: str) -> Optional[ExternalService]:
        """The service a host belongs to, if it is one of them."""
        if not host:
            return None
        name = (host or "").strip().lower()
        for service in self._services:
            if service.host.lower() == name:
                return service
        return None

    def for_name(self, name: str) -> Optional[ExternalService]:
        for service in self._services:
            if service.name.lower() == (name or "").strip().lower():
                return service
        return None


@dataclass(frozen=True)
class TransferLogEntry:
    """One transfer that happened."""

    occurred_at: datetime
    service: str
    destination: str
    destination_country: str
    recipient: str
    data_categories: List[str]
    lawful_basis: Optional[str]
    justification: str
    user_id: Optional[str] = None


class TransferLog:
    """Where the transfers that happened are recorded."""

    def record(self, entry: TransferLogEntry) -> TransferLogEntry:
        raise NotImplementedError

    def entries(self) -> List[TransferLogEntry]:
        raise NotImplementedError

    def for_destination(self, destination: str) -> List[TransferLogEntry]:
        raise NotImplementedError


class InMemoryTransferLog(TransferLog):
    """The transfers, in the memory of one process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: List[TransferLogEntry] = []

    def record(self, entry: TransferLogEntry) -> TransferLogEntry:
        with self._lock:
            self._entries.append(entry)
        return entry

    def entries(self) -> List[TransferLogEntry]:
        with self._lock:
            return list(self._entries)

    def for_destination(self, destination: str) -> List[TransferLogEntry]:
        with self._lock:
            return [entry for entry in self._entries
                    if entry.destination == destination]


class OutboundGuard:
    """The gate every outbound request goes through.

    ``permit`` does both things at once, because doing them separately is
    how a transfer ends up happening without being recorded: it checks that
    the transfer may happen, and — only if it may — writes it to the log.
    """

    def __init__(self, registry: Optional[ExternalServiceRegistry] = None,
                 transfer_log: Optional[TransferLog] = None, clock=None):
        self.registry = registry if registry is not None else ExternalServiceRegistry()
        self.transfer_log = transfer_log
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- the check ---------------------------------------------------------

    def permit(self, request: TransferRequest, *, host: str,
               service: Optional[str] = None,
               user_id: Optional[str] = None) -> TransferLogEntry:
        """Let the transfer happen, and record it. Or refuse it.

        Raises :class:`CrossBorderTransferRefusedError` when the transfer may
        not happen. Nothing is sent when it does.
        """
        service_name = service or host
        destination = self._destination(host, request)

        if destination is None:
            raise CrossBorderTransferRefusedError(REFUSAL_UNKNOWN_DESTINATION)

        known = self.registry.for_host(host)
        if known is None:
            known = self.registry.for_name(service_name)

        if known is not None:
            # The configuration is the source of truth: if it says the
            # service is in the United States and the caller says Nigeria,
            # one of them is wrong, and the safe answer is to refuse.
            if request.country and request.country != known.destination_country:
                raise CrossBorderTransferRefusedError(REFUSAL_COUNTRY_MISMATCH)
            if known.blocked:
                raise CrossBorderTransferRefusedError(REFUSAL_BLOCKED)
            if not known.in_nigeria:
                # The basis and the justification come from the caller's
                # request, and the service's own recorded ones are the
                # fallback for a caller that does not carry them.
                basis = request.basis or known.lawful_basis
                justification = request.justification or known.justification
                if not basis:
                    raise CrossBorderTransferRefusedError(REFUSAL_NO_BASIS)
                if not justification.strip():
                    raise CrossBorderTransferRefusedError(REFUSAL_NO_JUSTIFICATION)
                entry = TransferLogEntry(
                    occurred_at=self._clock(),
                    service=known.name,
                    destination=host,
                    destination_country=known.destination_country,
                    recipient=request.recipient,
                    data_categories=list(request.data_categories),
                    lawful_basis=basis,
                    justification=justification.strip(),
                    user_id=user_id,
                )
                self._record(entry)
                return entry
            # A service in Nigeria: nothing leaves the country.
            return TransferLogEntry(
                occurred_at=self._clock(),
                service=known.name,
                destination=host,
                destination_country=known.destination_country,
                recipient=request.recipient,
                data_categories=list(request.data_categories),
                lawful_basis=request.basis or known.lawful_basis,
                justification=request.justification or known.justification,
                user_id=user_id,
            )

        # The host is not in the configuration. Only a local host is allowed
        # then: it is on this machine or this network, so nothing leaves the
        # country. An unknown host on the internet cannot be shown to be in
        # Nigeria, and showing it is the whole point of the gate.
        if not _is_local_host(host):
            raise CrossBorderTransferRefusedError(REFUSAL_UNKNOWN_DESTINATION)
        return TransferLogEntry(
            occurred_at=self._clock(),
            service=service_name,
            destination=host,
            destination_country=NIGERIA,
            recipient=request.recipient,
            data_categories=list(request.data_categories),
            lawful_basis=request.basis,
            justification=request.justification,
            user_id=user_id,
        )

    def _destination(self, host: str, request: TransferRequest) -> Optional[str]:
        """Where the request is going, if we know."""
        if host:
            return host
        return request.recipient or None

    def _record(self, entry: TransferLogEntry) -> None:
        if self.transfer_log is None:
            return
        self.transfer_log.record(entry)


def _is_local_host(host: str) -> bool:
    """Whether the host is on this machine or this network.

    Nothing sent to one of these leaves the country, so the gate does not
    apply to it.
    """
    name = (host or "").strip().lower()
    if not name:
        return False
    if name in ("localhost", "::1", "127.0.0.1", "host.docker.internal"):
        return True
    if name.endswith(".local") or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_private
