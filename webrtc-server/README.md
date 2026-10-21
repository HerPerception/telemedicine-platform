# The media server

The video consultations, carried by a server **this practice runs itself, in Nigeria**. There is no
Twilio, no Agora and no LiveKit Cloud: the patient and the clinician both connect to the server
here, and the picture and the sound never leave the country.

## To run it locally

```bash
cd webrtc-server
cp .env.example .env      # then fill in the keys and the passwords
docker compose up
```

That is the whole of it. The API key and the secret in `.env` are the two halves of the credential
the application signs access tokens with; **the secret is the whole of the gate** — anybody who has
it can mint a token for any room, so it lives in the application's environment and nowhere else.

## What each of the four is

| | What it does | Why it is here |
| --- | --- | --- |
| **livekit** | the media server: it carries the picture and the sound | it is the only thing that sees the consultation |
| **coturn** | the TURN server: it relays when two phones cannot reach each other | on a mobile network that is most of the time — the phone is behind a carrier-grade NAT |
| **redis** | LiveKit's shared state | LiveKit's own requirement |
| **minio** | the bucket the recordings go into | the recording stays in Nigeria, on this machine |

## The ports, and who needs them

| Port | Who | |
| --- | --- | --- |
| 7880 | the browsers | the signalling websocket |
| 7881 | the browsers | the media over TCP, for the networks where UDP is blocked |
| 7882 | the browsers | the media over UDP, the usual path |
| 3478, 5349, 49160–49200 | the browsers | the TURN relay |
| 9000, 9001 | the practice | the bucket and its console |
| 5432, 8080 | the practice | the application's database and API — **not** published by this file |

**Only the media ports have to be open to the world**, because the two parties are on their own
networks. The application's own API is on a different port, behind the practice's own
authentication, and the LiveKit server's secret never leaves the application.

**The only way into a consultation is a token.** The application is the only holder of the secret,
and it issues a token only to the booked patient and the clinician who delivers the appointment.
A token names one room — `consultation_<id>` — and is good for two hours.

## Telling the server its public address

`LIVEKIT_NODE_IP` and `external-ip` in `turnserver.conf` have to be the **public** address of the
machine, not its private one. If the server is behind a router, that is the address the ports are
forwarded to. Without it the two peers try to reach each other through an address that is not
theirs, and the call does not connect.

The domains in `livekit.yaml` and `turnserver.conf` are the practice's own — `video.example.ng` in
the examples.

## The recording

**Off by default.** Two things have to be true before a consultation is recorded:

1. `TELEMEDICINE_RECORDING_ENABLED` is on in the application's environment, and
2. the patient has consented to the consultation being recorded — the `consultation_recording`
   consent, which is a consent of its own like the other optional uses.

Without the consent, the application issues no media token at all for that consultation, and says
why.

The recording itself is made by the media server and written to the local bucket. It is not
encrypted by the application — the bucket holds it, and the bucket is on this machine, in this
country. **What happens to a recording when the practice no longer needs it is the retention
policy's business, and the policy is still switched off.**

## What is not here

- **A public address.** A server on a home connection in Nigeria is behind a router, and the
  ports have to be forwarded. A practice that wants a reliable address needs a host in Nigeria, and
  the choice of one is the practice's.
- **A certificate.** The websocket is `wss://`, so the server needs a certificate for the
  practice's domain. The reverse proxy in front of the application is where it usually goes.
- **A scale-out.** One server is enough for a practice. LiveKit can be split across machines, and
  Redis is already here for it.
