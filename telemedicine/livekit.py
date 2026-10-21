"""The LiveKit access token.

A LiveKit access token is a JSON Web Token signed with HMAC-SHA256 using the
server's API secret. The project has one dependency and it is the PostgreSQL
driver, so the token is built with the standard library rather than with the
LiveKit SDK — the format is short, and the standard library has everything
it needs.

**The format, and where it comes from.** The LiveKit server verifies a token
in `livekit/protocol/auth` and accepts it in `livekit/livekit/pkg/service/auth.go`.
What that code requires is:

* the signature is **HS256**, and nothing else;
* the issuer (``iss``) is the **API key** the token was signed for;
* the subject (``sub``) is the **identity** of the participant;
* the **expiration is required** — a token without one is refused, so that a
  hand-rolled minter cannot mint a permanent credential;
* the video grant is in the payload under ``video``, with the room in
  ``video.room`` and ``video.roomJoin`` set, or the join is refused.

The grant is written the way the Go type is written: ``canPublish`` and
``canSubscribe`` are pointers there, and a grant that sets neither of them
grants everything — so both are written explicitly here, and the room is
named.

The token is **not encrypted**: anyone holding it can read what is in it, and
it can be used until it expires. It therefore carries an identity, a room and
a lifetime, and nothing else — no clinical information, no name, no reason
for the consultation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Dict, Optional

# How long a token is good for. Two hours: long enough for a consultation
# and the waiting room around it, short enough that a leaked token does not
# open a room tomorrow.
DEFAULT_TTL_SECONDS = 2 * 60 * 60

# The prefix of a room name. The consultation's id follows it.
ROOM_PREFIX = "consultation_"


class TokenError(ValueError):
    """The token could not be built, or could not be read."""


def room_name(consultation_id: str) -> str:
    """The room a consultation happens in."""
    if not consultation_id or not str(consultation_id).strip():
        raise TokenError("a consultation needs an id")
    return f"{ROOM_PREFIX}{str(consultation_id).strip()}"


def issue_access_token(api_key: str, api_secret: str, *, identity: str,
                       room: str, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                       name: Optional[str] = None,
                       can_publish: bool = True,
                       can_subscribe: bool = True,
                       can_publish_data: bool = True,
                       now: Optional[int] = None) -> str:
    """A LiveKit access token.

    The claims are the ones the server reads:

    ``iss``  the API key
    ``sub``  the identity of the participant
    ``iat``  when the token was issued
    ``nbf``  when the token becomes valid
    ``exp``  when it stops being valid
    ``video`` the grant: the room, and what the participant may do in it
    """
    if not api_key or not api_secret:
        raise TokenError("the LiveKit API key and secret are needed to sign a token")
    if not identity or not str(identity).strip():
        raise TokenError("a token needs an identity")
    if not room or not str(room).strip():
        raise TokenError("a token needs a room")

    issued = int(now if now is not None else time.time())
    expires = issued + int(ttl_seconds)

    payload: Dict[str, object] = {
        "iss": api_key,
        "sub": str(identity).strip(),
        "iat": issued,
        "nbf": issued,
        "exp": expires,
        "identity": str(identity).strip(),
        "video": {
            "room": str(room).strip(),
            "roomJoin": True,
            "roomCreate": False,
            "canPublish": bool(can_publish),
            "canSubscribe": bool(can_subscribe),
            "canPublishData": bool(can_publish_data),
        },
    }
    if name:
        payload["name"] = str(name)

    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join([
        _b64(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")),
        _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")),
    ])
    signature = hmac.new(api_secret.encode("utf-8"), signing_input.encode("utf-8"),
                         hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def verify_access_token(api_key: str, api_secret: str, token: str,
                        now: Optional[int] = None) -> Dict:
    """The claims of a token, if it is ours and it is still valid.

    This is what the application uses to check its own tokens — the ones it
    issued — and what the tests use to prove that a token is well formed.
    """
    if not token or token.count(".") != 2:
        raise TokenError("a token has three parts")
    header_part, payload_part, signature_part = token.split(".")

    expected = hmac.new(api_secret.encode("utf-8"),
                         f"{header_part}.{payload_part}".encode("utf-8"),
                         hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64(signature_part), expected):
        raise TokenError("the signature does not match")

    try:
        header = json.loads(_unb64(header_part).decode("utf-8"))
        payload = json.loads(_unb64(payload_part).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise TokenError(f"the token could not be read: {error}") from None

    if header.get("alg") != "HS256":
        raise TokenError(f"the token is signed with {header.get('alg')}, not HS256")
    if payload.get("iss") != api_key:
        raise TokenError("the token was issued for another key")
    expires = payload.get("exp")
    if expires is None:
        raise TokenError("the token never expires, which is not allowed")
    if int(now if now is not None else time.time()) >= int(expires):
        raise TokenError("the token has expired")
    return payload


def _b64(raw: bytes) -> str:
    """Base64, without the padding, the way JWT writes it."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    """The other way round, with the padding put back."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)
