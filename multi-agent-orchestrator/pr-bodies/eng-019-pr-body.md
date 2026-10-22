# ENG-019: the media server, in Nigeria, and the token that opens a consultation

The consultations are carried by a server the practice runs itself, in
Nigeria. There is no Twilio, no Agora and no LiveKit Cloud, and the media
never leaves the country: a managed video service abroad is a transfer of
the patient's picture and voice, and the patient cannot be asked to consent
to it at the moment of booking.

webrtc-server/ holds the four containers: LiveKit (the media), coturn (the
relay, for the mobile networks where two phones cannot reach each other),
Redis, and MinIO (the bucket the recordings go into, here, in Nigeria).

The token is a JSON Web Token signed with HMAC-SHA256, built with the
standard library rather than with the LiveKit SDK, because the project has
one dependency and it is the PostgreSQL driver. **The format is not a
guess**: it is the one the LiveKit server verifies, read from the server's
own code -- the claims and the signing from
livekit/protocol/auth/accesstoken.go, the grant's field names from
grants.go, and what the server checks from verifier.go and
livekit/pkg/service/auth.go: HS256 and nothing else, the issuer must be the
API key, the expiration is required, and the room comes from video.room.

The token carries an identity, a room and a lifetime, and nothing else: it
is not encrypted, so it holds no name, no diagnosis and no reason for the
consultation. It is good for two hours.

POST /video/consultations/{id}/video-token issues it, and the rules are
the ones that already apply to the consultation: the booked patient and the
clinician who delivers the appointment, and nobody else.

**Recording is off by default, and it needs the patient's consent even
when it is on.** Recording the consultation is an optional use like the
others, so it has its own consent -- consultation_recording -- in the
consent record, and its own paragraph in the privacy notice. When the
recording is switched on and the patient has not consented, no media token
is issued at all, and the refusal says why.

The client page shows the waiting room, and the camera and the microphone
are not turned on until the patient presses the button.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
