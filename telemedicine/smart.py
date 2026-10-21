"""SMART on FHIR: launching the application from a hospital's record.

**This is off by default, and the MVP does not need it.** A practice that
is not connected to a hospital signs in the ordinary way, and nothing here
touches that. The flag is ``TELEMEDICINE_SMART_FHIR_ENABLED`` and the
endpoints are not even registered when it is off.

**What it is for.** SMART on FHIR is how an electronic health record launches
an application: the clinician clicks the app inside the record, the record
sends the browser to the application with a code, and the application
exchanges that code for a token.

**The client is a public client.** It keeps no secret - a secret in a
repository is a secret in everybody's repository - and it proves that it is
the one that started the flow with **PKCE** (RFC 7636): it sends a hash of
a random verifier in the authorization request, and the verifier itself in
the token request. The record can check that they match, which is what stops
another application from using a code it intercepted.

**The state is signed.** The state carries the PKCE verifier, so it has to
survive the round trip through the browser unchanged; it is signed with the
application's own secret, and a state that does not verify is refused. A
verifier that could be changed in the browser would defeat the point of
PKCE.

**The account has to be known.** The record says who the clinician is; the
application has to know which of its own accounts that is. The mapping is in
``config/smart_clients.yaml`` under ``identity.<the record's identity>``.
**A clinician with no line there is refused**: the practice decides who its
clinicians are, and the record does not.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telemedicine.errors import ValidationError

# The path the record asks for. It is fixed by the SMART specification, and
# it is at the root of the server rather than under the API.
DISCOVERY_PATH = "/.well-known/smart-configuration"

# The capabilities this client has. "client-public" says the client keeps
# no secret and uses PKCE, which is what it does.
CAPABILITIES = ("launch-ehr", "client-public")

# How long a state is good for. The flow is a redirect and a redirect back:
# minutes, not hours.
STATE_TTL_SECONDS = 600

DEFAULT_CONFIG_PATH = (Path(__file__).resolve().parent.parent / "config"
                       / "smart_clients.yaml")


class SmartError(ValidationError):
    """The SMART flow could not be completed."""


class SmartNotConfigured(SmartError):
    """SMART is not switched on, or it is not configured."""


@dataclass(frozen=True)
class SmartConfiguration:
    """The client registration, and who may sign in through it."""

    enabled: bool = False
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    issuer: str = ""
    client_id: str = ""
    redirect_uri: str = ""
    scopes: Tuple[str, ...] = ()
    identities: Dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        """Whether the client registration is complete enough to be used.

        Whether the feature is *on* is a separate question, and the
        environment answers it: the file says what the default is, and the
        deployment may switch it on or off.
        """
        return bool(self.client_id and self.authorization_endpoint
                    and self.token_endpoint and self.redirect_uri)

    def account_for(self, identity: str) -> Optional[str]:
        """The local account an identity from the record maps to."""
        if not identity:
            return None
        return self.identities.get(identity.strip().lower())


def load_configuration(path=None) -> SmartConfiguration:
    """The client registration, read from the configuration file."""
    from telemedicine.yaml_lite import (
        ConfigurationError,
        as_bool,
        read_flat_yaml_file,
    )

    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        values = read_flat_yaml_file(path)
    except ConfigurationError as error:
        raise SmartNotConfigured(f"{path}: {error}") from None

    def text(name: str, default: str = "") -> str:
        """A value, unless it is still a placeholder.

        The file that ships has ``REPLACE_WITH_...`` where the practice's
        own values go. A placeholder is not a value: a client registration
        with one in it is not a registration.
        """
        value = (values.get(f"smart.{name}") or default).strip()
        if value.startswith("REPLACE_WITH"):
            return ""
        return value

    identities: Dict[str, str] = {}
    for key, value in values.items():
        if key.startswith("identity."):
            identity = key[len("identity."):].strip().lower()
            local = (value or "").strip()
            if local.startswith("REPLACE_WITH"):
                local = ""
            if identity and local:
                identities[identity] = local

    scopes = text("scopes").split()
    return SmartConfiguration(
        enabled=as_bool(values.get("smart.enabled", "false") or "false",
                        "smart.enabled", path),
        authorization_endpoint=text("authorization_endpoint"),
        token_endpoint=text("token_endpoint"),
        userinfo_endpoint=text("userinfo_endpoint"),
        issuer=text("issuer"),
        client_id=text("client_id"),
        redirect_uri=text("redirect_uri"),
        scopes=tuple(scopes),
        identities=identities,
    )


def discovery_document(configuration: SmartConfiguration) -> dict:
    """The document at ``/.well-known/smart-configuration``.

    This is how a record finds out where to send the browser. The three
    fields the task named are here, and the rest are the ones the SMART
    specification expects a record to read.
    """
    return {
        "authorization_endpoint": configuration.authorization_endpoint,
        "token_endpoint": configuration.token_endpoint,
        "capabilities": list(CAPABILITIES),
        # The rest of what a record reads.
        "issuer": configuration.issuer,
        "scopes_supported": list(configuration.scopes),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    }


# --------------------------------------------------------------------------
# PKCE
# --------------------------------------------------------------------------


def new_verifier() -> str:
    """A random PKCE verifier."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """The S256 challenge for a verifier: the base64 of its SHA-256."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --------------------------------------------------------------------------
# The state
# --------------------------------------------------------------------------


def sign_state(payload: dict, secret: str, now: Optional[int] = None) -> str:
    """A state the browser cannot change.

    The state carries the PKCE verifier, so it has to come back unchanged;
    it is signed, and a state that does not verify is refused.
    """
    issued = int(now if now is not None else time.time())
    body = dict(payload)
    body["iat"] = issued
    body["exp"] = issued + STATE_TTL_SECONDS
    encoded = base64.urlsafe_b64encode(
        json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("utf-8"),
                         hashlib.sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def verify_state(state: str, secret: str, now: Optional[int] = None) -> dict:
    """The payload of a state, if it is ours and it has not expired."""
    if not state or "." not in state:
        raise SmartError("the state is missing or malformed")
    encoded, _, signature = state.partition(".")
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("utf-8"),
                         hashlib.sha256).digest()
    try:
        given = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    except (ValueError, TypeError):
        raise SmartError("the state is malformed") from None
    if not hmac.compare_digest(given, expected):
        raise SmartError("the state was not signed by this application")
    try:
        payload = json.loads(base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SmartError("the state could not be read") from None
    moment = int(now if now is not None else time.time())
    if moment >= int(payload.get("exp", 0)):
        raise SmartError("the state has expired")
    return payload


# --------------------------------------------------------------------------
# The flow
# --------------------------------------------------------------------------


def start_flow(configuration: SmartConfiguration, secret: str,
               launch: Optional[str] = None) -> Tuple[str, str]:
    """Begin the flow: the state, and where the browser goes.

    The verifier is random, and the challenge is its hash. The verifier
    goes into the signed state, so that it comes back unchanged; the
    challenge goes to the record, so that the record can check it later.
    """
    if not configuration.configured:
        raise SmartNotConfigured("the SMART client is not configured")
    verifier = new_verifier()
    state = sign_state({"code_verifier": verifier, "launch": launch or ""}, secret)
    url = authorization_url(configuration, state,
                            challenge=code_challenge(verifier), launch=launch)
    return state, url


def authorization_url(configuration: SmartConfiguration, state: str,
                      challenge: str, launch: Optional[str] = None) -> str:
    """Where the browser goes to sign in through the record.

    The parameters are the ones the SMART specification asks for: the
    client, the redirect, the response type, the scopes, the state, and the
    PKCE challenge.
    """
    if not configuration.configured:
        raise SmartNotConfigured("the SMART client is not configured")
    parameters = {
        "client_id": configuration.client_id,
        "redirect_uri": configuration.redirect_uri,
        "response_type": "code",
        "scope": " ".join(configuration.scopes),
        "state": state,
        "aud": configuration.issuer or configuration.authorization_endpoint,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if launch:
        parameters["launch"] = launch
    parameters = {key: value for key, value in parameters.items() if value}
    separator = "&" if "?" in configuration.authorization_endpoint else "?"
    return configuration.authorization_endpoint + separator + urllib.parse.urlencode(parameters)


@dataclass(frozen=True)
class LaunchedCode:
    """What the record sent back."""

    code: str
    state: str
    identity: str


def exchange_code(configuration: SmartConfiguration, code: str, verifier: str,
                 timeout: int = 30) -> dict:
    """Exchange the code for a token, at the record's own token endpoint.

    This is the step that proves the flow was ours: the verifier is sent,
    and the record checks it against the challenge it was given.
    """
    if not configuration.configured:
        raise SmartNotConfigured("the SMART client is not configured")
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": configuration.redirect_uri,
        "client_id": configuration.client_id,
        "code_verifier": verifier,
    }).encode("ascii")
    request = urllib.request.Request(
        configuration.token_endpoint, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SmartError(
            f"the record refused the code: {error.read().decode('utf-8', 'replace')}"
        ) from None
    except (urllib.error.URLError, OSError) as error:
        raise SmartError(f"the record could not be reached: {error}") from None
    if not payload.get("access_token"):
        raise SmartError("the record returned no access token")
    return payload


def fetch_identity(configuration: SmartConfiguration, access_token: str,
                   timeout: int = 30) -> str:
    """Who the clinician is, according to the record."""
    if not configuration.userinfo_endpoint:
        raise SmartNotConfigured("the record's userinfo endpoint is not configured")
    request = urllib.request.Request(
        configuration.userinfo_endpoint,
        headers={"Authorization": f"Bearer {access_token}",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as error:
        raise SmartError(f"the record could not be reached: {error}") from None
    identity = payload.get("email") or payload.get("preferred_username") or ""
    if not identity:
        raise SmartError("the record did not say who the clinician is")
    return str(identity).strip().lower()
