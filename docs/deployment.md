# Running the telemedicine platform

- **Feature:** `OPS-002 (pre-work)` — the parts of a deployment that live in the repository
- **Status:** the container, the settings and the runbook are here and tested. **The deployment
  itself is not made**: it needs a machine, a domain, a certificate and the four answers in §7.
- **Owner:** `OpenCode-20261020-3dafd2c8`

## 1. What a deployment is

Three things, and nothing else:

| | What it is | What it does |
| --- | --- | --- |
| **the API** | one container | serves the FHIR R4 API and the video rooms, and signs people in |
| **the delivery worker** | one container, the same image | empties the queue of confirmations and sends them |
| **the database** | PostgreSQL | holds every record: the patients, the appointments, the prescriptions, the audit trail |

And one thing that is not a container: **a proxy in front of them that terminates TLS**. The
application speaks plain HTTP, so something has to speak HTTPS to the outside world. That is where the
certificate lives, and where the rate limits and the request logging belong.

The delivery worker and the API are the same image with a different command, so they always have the
same code and the same settings. Run **one** delivery worker: two of them would send some
confirmations twice.

## 2. What it needs

Every setting is an environment variable. Nothing is read from a file, and the database password is
never written anywhere.

| Variable | What it is | Without it |
| --- | --- | --- |
| `TELEMEDICINE_DATABASE_URL` | The PostgreSQL connection string | The application keeps its records in memory and loses them when it stops |
| `TELEMEDICINE_HOST` | The interface to listen on | `127.0.0.1` — the safe default, because a server that listens everywhere by accident answers on a network it was never meant to |
| `TELEMEDICINE_PORT` | The port | `8080` |
| `TELEMEDICINE_AUDIT_ANCHOR` | The file the audit chain is anchored to | The audit trail is not anchored, and a chain that was rewritten from the beginning cannot be told apart from an untouched one |
| `TELEMEDICINE_TRUST_FORWARDED_FOR` | Whether to believe the address a proxy reports | `false`. Turn it on **only** behind a proxy that replaces the header, or every caller is counted as the proxy and everybody is locked out at once |
| `TELEMEDICINE_SMTP_HOST` | The mail server | The delivery worker refuses to start, and no confirmation is ever sent |
| `TELEMEDICINE_SMTP_PORT` | Its port | `25` |
| `TELEMEDICINE_SMTP_FROM` | The address the messages come from | `telemedicine@localhost` |
| `TELEMEDICINE_SMTP_USERNAME` | The user to log in as | None |
| `TELEMEDICINE_SMTP_PASSWORD` | Its password | None. It is read from the environment and written nowhere: not to the log, not to the audit trail, not to the outbox, not into the message |
| `TELEMEDICINE_SMTP_TLS` | Whether to start TLS | `true` |
| `TELEMEDICINE_DELIVERY_INTERVAL` | How long the worker waits between passes | `30` seconds |
| `TELEMEDICINE_TRANSFER_SERVICES` | Where the external services are described — which country each is in, and the basis and justification recorded for it | `config/external_services.yaml` |
| `TELEMEDICINE_SMTP_LAWFUL_BASIS` | The basis for sending health data to the mail server, when it is outside Nigeria: `consent`, `contract`, `vital_interest`, `public_interest` or `legal_claim` | none — and without it, a mail server outside Nigeria is **refused** |
| `TELEMEDICINE_SMTP_JUSTIFICATION` | What the transfer is for, in the practice's own words | none — and without it, a mail server outside Nigeria is **refused** |
| `TELEMEDICINE_LIVEKIT_HOST` | Where the media server is — the practice's own server, in Nigeria | none — and without it there are no video consultations |
| `TELEMEDICINE_LIVEKIT_URL` | What the browser connects to: `wss://video.example.ng` | none |
| `TELEMEDICINE_LIVEKIT_API_KEY` | The key the media server is configured with | none — and without it there are no video consultations |
| `TELEMEDICINE_LIVEKIT_API_SECRET` | The secret the access tokens are signed with. **Only the application has it**, and it is the whole of the gate: anybody who has it can mint a token for any room | none |
| `TELEMEDICINE_RECORDING_ENABLED` | Whether consultations are recorded at all | `false` — recording is off, and the patient's consent is needed as well |
| `TELEMEDICINE_RECORDING_CONSENT_REQUIRED` | Whether the patient's consent to the recording is required | `true` |
| `TELEMEDICINE_RECORDING_BUCKET` | The bucket the recordings go into: the local one, in Nigeria | none |
| `TELEMEDICINE_SMART_FHIR_ENABLED` | Whether the SMART-on-FHIR endpoints exist at all | `false` — **a practice that is not connected to a hospital does not need this**, and the ordinary sign-in is enough |
| `TELEMEDICINE_SMART_CLIENTS` | Where the client registration is: the record's addresses, the client id, and who may sign in | `config/smart_clients.yaml` |
| `TELEMEDICINE_SMART_STATE_SECRET` | The secret the redirect state is signed with. Without it, a state cannot be checked and the flow is refused | none — and with it unset, SMART cannot be used |

## 3. Bringing it up

The repository has a compose file for a staging environment: the API, the delivery worker and a
database.

```bash
cp .env.example .env      # then change the passwords in it
docker compose up -d database
docker compose run --rm api python3 scripts/apply_schema.py \
    "postgresql://telemedicine:${POSTGRES_PASSWORD}@database:5432/telemedicine"
docker compose up -d api delivery
```

The schema is applied **once**, as a deployment step, and not by the application when it starts: a
process that starts should not change the shape of the database underneath it. The schema files are
re-runnable, so applying them again is safe and is how a deployment is upgraded.

## 4. Knowing that it is working

```bash
docker compose exec api python3 scripts/healthcheck.py
```

It asks two questions and prints the answers: **is the server answering?** (the public metadata
endpoint, which touches nothing) and **is the database there, and does it have the schema?** The
container's own `HEALTHCHECK` runs the same script every thirty seconds, so an orchestrator knows
without being asked.

The audit trail can be checked at any time:

```bash
docker compose exec api python3 scripts/verify_audit_chain.py \
    "$TELEMEDICINE_DATABASE_URL" "$TELEMEDICINE_AUDIT_ANCHOR"
```

It checks the chain internally, and then against the anchors that were published outside the
database. **A chain that was rewritten from the beginning verifies internally and fails here** — which
is the whole reason the anchors exist.

## 4a. The media server

The video consultations are carried by a server the practice runs itself, in Nigeria. It is a
separate set of containers, in `webrtc-server/`, and it is started on its own:

```bash
cd webrtc-server && cp .env.example .env   # then fill in the keys
docker compose up
```

The application is told where it is with `TELEMEDICINE_LIVEKIT_HOST`, `TELEMEDICINE_LIVEKIT_URL`,
`TELEMEDICINE_LIVEKIT_API_KEY` and `TELEMEDICINE_LIVEKIT_API_SECRET`. **The secret is the whole of
the gate**: the application is the only holder of it, and it issues a token only to the booked
patient and the clinician who delivers the appointment. There is no third-party service involved —
no Twilio, no Agora, no LiveKit Cloud — and the media never leaves the country.

`webrtc-server/README.md` has the ports, the public address the server needs, and the recording.

## 4b. SMART on FHIR (off by default)

**Leave it off.** SMART on FHIR is how a hospital's electronic health record launches an
application: the clinician clicks the app inside the record, the record sends the browser to the
application with a code, and the application exchanges that code for a token. A practice that is
not connected to a hospital does not need it, and with `TELEMEDICINE_SMART_FHIR_ENABLED` unset the
endpoints are not registered at all — the ordinary sign-in is the only way in, exactly as before.

The registration is in `config/smart_clients.yaml`: the record's own addresses, the client id the
record has registered, and the identities that may sign in and the local account each of them is.
**The client keeps no secret** — it proves that it started the flow with PKCE instead — so there is
nothing to leak from the repository. The state is signed with `TELEMEDICINE_SMART_STATE_SECRET`,
which is the one secret the feature needs.

## 5. The audit anchors

The anchors are the digests of the audit chain, published outside the database so that a rewritten
chain can be detected. They are on a volume in the compose file, so they survive a restart.

**Copy them off the machine.** An anchor on the same disk as the application is worth exactly what
an attacker with write access to that disk is worth. Where they go is a decision for the practice:
a machine that does not run the application, the practice's own records, a service the application
cannot write to. The format is one JSON object per line, so anything can read them.

## 6. Backups

The database holds every record, and it is the only thing worth backing up. The audit log is inside
it, and the anchors are outside it, so **a backup of the database without the anchors is not enough
to prove the trail was not tampered with** — keep both.

```bash
docker compose exec database pg_dump -U telemedicine telemedicine > telemedicine-$(date +%F).sql
```

There is no restore procedure in the repository yet, and there should be one before anything real is
in there: the restore has to be *tested*, not merely possible.

## 7. What has to be answered before a real patient is in there

The compliance review (`docs/reviews/compliance-review.md`) and its status
(`docs/reviews/remediation-status.md`) have the detail. Four questions are the practice's, not the
engineering's, and they are listed in the review as REG-01, REG-02, PRIV-02 and PRIV-03:

1. **Where is the practice, and where are the patients?** Nothing about the law, the drug codes,
   consent or retention can be settled without this.
2. **Which drug code system do the prescriptions have to use?** A prescription that identifies a
   medicine with an invented code cannot be dispensed.
3. **What do patients have to agree to, and how is that agreement recorded?** Consent capture is not
   built.
4. **How long are records kept, and what happens to them at the end?** Nothing is ever deleted, and
   there is no policy behind it.

Two more things are engineering work and are not done:

- **A media provider.** The video rooms have the rules — who may join, when, the waiting room, the
  tokens — but no transport carries the picture or the sound.
- **The proxy.** TLS, the rate limits, the request logging and the certificate.

## 8. Upgrading

1. Take a backup of the database **and** the anchors.
2. Apply the schema again: it is re-runnable, and the new statements are guarded.
3. Rebuild and restart the image.
4. Check the health, and check the chain.

The application never changes the schema itself, and the schema files only ever add what is missing.
