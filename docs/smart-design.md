# SMART on FHIR

- **Feature:** ENG-020 — launching the application from a hospital's record
- **Status:** implemented, **switched off**, and marked as not needed for the MVP
- **Why it is off:** a practice that is not connected to a hospital does not need it, and the
  ordinary sign-in is enough. The endpoints are not registered at all while it is off, so nothing
  about the application changes.

## What it is

SMART on FHIR is how an electronic health record launches an application: the clinician clicks the
app inside the record, the record sends the browser to the application with a code, and the
application exchanges that code for a token.

The record is the authorization server; the application is the client.

## The three endpoints

With the flag on, three endpoints at the root of the server — the record looks for the discovery
document at `/.well-known/smart-configuration`, and it cannot be anywhere else.

| | |
| --- | --- |
| `GET /.well-known/smart-configuration` | how the record finds out where to send the browser |
| `GET /smart/authorize` | the application sends the browser to the record, with the scopes, a signed state and a PKCE challenge |
| `GET /smart/callback` | the record sends the browser back with a code; the application exchanges it, asks the record who the clinician is, and signs them in |

The discovery document answers the three things the task named — `authorization_endpoint`,
`token_endpoint` and the capabilities `["launch-ehr", "client-public"]` — and the rest of what a
record reads: the issuer, the scopes, the response and grant types, and the code challenge methods.

## The client is a public client, and it proves itself

**It keeps no secret.** A secret in a repository is a secret in everybody's repository, so there
is none: the client proves that it is the one that started the flow with **PKCE** (RFC 7636). It
sends the hash of a random verifier in the authorization request and the verifier itself in the
token request, and the record checks that they match. That is what stops another application from
using a code it intercepted.

**The state is signed.** The state carries the verifier — it has to come back through the browser
unchanged — so it is signed with the application's own secret, and a state that does not verify is
refused. A verifier that could be changed in the browser would defeat the point of PKCE.

## Who may sign in

The record says who the clinician is; the application has to know which of its own accounts that is.
The mapping is in `config/smart_clients.yaml`:

```yaml
identity.clinician@example.ng: 8f2c...-the-local-account-id
```

**A clinician with no line there is refused**, and the refusal says so. The practice decides who
its clinicians are; the record does not.

## The flag

| | |
| --- | --- |
| `TELEMEDICINE_SMART_FHIR_ENABLED` | whether the endpoints exist. Unset or `false` is off |
| `TELEMEDICINE_SMART_CLIENTS` | where the registration is: `config/smart_clients.yaml` |
| `TELEMEDICINE_SMART_STATE_SECRET` | the secret the state is signed with |

The environment variable overrides the flag in the file, so a deployment can switch it on without
editing the repository.

**With the flag off, the application is not mounted at all**: the router carries the two surfaces
it has always had, and the ordinary sign-in is the only way in. There is a test for that, and it is
the first thing in the test file.

## What it is not

- **The application is not an OAuth2 server.** It is a client: it launches *from* a record. Nothing
  here lets another application ask this one for access to a patient's record, and nothing in the
  MVP needs that.
- **It is not a way into the records without the ordinary sign-in.** The token it gets from the
  record is used to talk to the record, not to this application.
- **It does not map a record's patient to a local patient.** The launch context is carried, and
  the identity mapping is about the *clinician* who launched it. Reading a patient's record from
  the record, and bringing it into this application, is a separate piece of work, and a practice
  that has no hospital connection does not need it.
