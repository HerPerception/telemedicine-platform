# The media server, and the token that opens a consultation

- **Feature:** ENG-019 — the video consultations, carried by a server the practice runs itself, in
  Nigeria
- **Why:** section 41 of the Nigeria Data Protection Act 2023 forbids transferring personal data out
  of Nigeria without an adequate basis. A managed video service in another country is a transfer of
  the patient's picture and voice, and the patient cannot be asked to consent to it at the moment of
  booking. So the media server is the practice's own, in the country, and nothing leaves it.

## What is where

| | |
| --- | --- |
| `webrtc-server/` | the media server, the TURN server, the bucket, and the client page |
| `telemedicine/livekit.py` | the access token: a JWT, signed with the standard library |
| `telemedicine/video.py` | `MediaConfiguration`, `MediaToken`, and `VideoService.media_token()` |
| `telemedicine/video_api.py` | `POST /video/consultations/{id}/video-token` |

## The token

A LiveKit access token is a JSON Web Token signed with HMAC-SHA256 using the server's API secret.
The project has one dependency and it is the PostgreSQL driver, so the token is built with the
standard library rather than with the LiveKit SDK.

**The format is not a guess.** It is the one the LiveKit server verifies, read from the server's
own code:

* `livekit/protocol/auth/accesstoken.go` — the claims, and the signing;
* `livekit/protocol/auth/grants.go` — the video grant and its field names;
* `livekit/protocol/auth/verifier.go` — what the server checks: HS256 and nothing else, the issuer
  must be the API key, and **the expiration is required** — a token without one is refused, so that
  a hand-rolled minter cannot mint a permanent credential;
* `livekit/livekit/pkg/service/auth.go` — the room name comes from `video.room`, and the join is
  refused without `video.roomJoin`.

The claims are:

```json
{
  "iss": "the API key",
  "sub": "the user id",
  "iat": 1792600000, "nbf": 1792600000, "exp": 1792607200,
  "identity": "the user id",
  "video": {
    "room": "consultation_<id>",
    "roomJoin": true, "roomCreate": false,
    "canPublish": true, "canSubscribe": true, "canPublishData": true
  }
}
```

**The token is not encrypted.** Anybody holding it can read what is in it, and it can be used until
it expires. So it carries an identity, a room and a lifetime, and nothing else — no name, no
diagnosis, no reason for the consultation. The tests check that.

**It is good for two hours**, which is long enough for a consultation and the waiting room around
it, and short enough that a leaked token does not open a room tomorrow.

## The endpoint

```
POST /video/consultations/{appointment_id}/video-token
```

**The rules are the ones that already apply** to the consultation: the booked patient and the
clinician who delivers the appointment, and nobody else. A stranger is refused with `403`, and the
refusal is audited.

The response carries the token, the room, the URL to connect to, the identity, what may be
published and subscribed to, whether the consultation is recorded, and when it expires.

## The waiting room

The waiting room is the domain's own, from ENG-004: the patient joins it and the clinician admits
them. The client page (`webrtc-server/client/index.html`) shows it, and **the camera and the
microphone are not turned on until the patient presses the button** — the token allows publishing,
but nothing is published until the patient says so.

The client page loads `livekit-client` from a CDN so that it works with nothing installed. **A
deployment that must not talk to a third party should vendor it** and change the script tag; the
library never sees the media, but a CDN does see which addresses load the page.

## The recording

**Off by default**, and it needs the patient's consent even when it is on.

The recording is an optional use like the others, so it has its own consent —
`consultation_recording` — in the consent record of ENG-015, and its own paragraph in the privacy
notice. **When the recording is switched on and the patient has not consented, no media token is
issued at all**, and the refusal says why. The other consents are not a consent to record.

The recording itself is made by the media server and written to the local bucket, on the practice's
own machine, in Nigeria. It is not encrypted by the application: the bucket holds it, and the bucket
is here.

**What happens to a recording when the practice no longer needs it is the retention policy's
business, and the policy is still switched off.**

## What is not here

- **A public address.** A server on a home connection is behind a router and the ports have to be
  forwarded. A practice that wants a reliable address needs a host in Nigeria, and the choice is
  the practice's.
- **A certificate.** The websocket is `wss://`, so the server needs a certificate for the
  practice's domain.
- **A way to see the recording from the application.** The bucket is a bucket; listing it is the
  practice's, and the application does not read it.
