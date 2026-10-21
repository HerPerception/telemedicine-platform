# telemedicine-platform
Personal telemedicine MVP - appointment booking, video consult, e-prescription + FHIR API

## A note on SMART on FHIR

**SMART-on-FHIR is only needed to connect to a hospital EHR like LUTH. Leave it OFF for
standalone use.**

SMART on FHIR is how a hospital's electronic health record launches an application: the clinician
clicks the app inside the record, the record sends the browser to the application with a code, and
the application exchanges that code for a token. It is for connecting to somebody else's record.

**A practice that runs on its own does not need it.** The flag is off, the endpoints are not
registered at all, and the ordinary sign-in is the only way in — exactly as it was before the
feature existed.

| | |
| --- | --- |
| The flag | `TELEMEDICINE_SMART_FHIR_ENABLED`, unset or `false` |
| The registration | `config/smart_clients.yaml` — the record's addresses, the client id, and who may sign in |
| The one secret | `TELEMEDICINE_SMART_STATE_SECRET`, which signs the redirect state |

The client keeps no secret of its own: it proves that it started the flow with PKCE, so there is
nothing in the repository to leak. `docs/deployment.md` §4b has the details, and
`docs/smart-design.md` has the design.

## The rest of it

- `docs/compliance/nigeria.md` — the law the practice is under, and the answers
- `docs/deployment.md` — what a deployment needs, and how to bring it up
- `docs/acceptance-traceability.md` — every acceptance criterion, and the test that covers it
- `webrtc-server/` — the video server the practice runs itself, in Nigeria
- `AGENTS.md` — the map of the repository
