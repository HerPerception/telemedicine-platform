# ENG-020: SMART on FHIR, built and switched off

SMART on FHIR is how a hospital's electronic health record launches an
application. A practice that is not connected to a hospital does not need
it, and the ordinary sign-in is enough -- so it is off, and the endpoints
are not registered at all while it is off. The application is exactly what
it was before this feature existed, and there is a test that says so.

With the flag on, three endpoints at the root of the server, because a
record looks for the discovery document at /.well-known/smart-configuration
and cannot be told to look anywhere else:

  GET /.well-known/smart-configuration   how the record finds us
  GET /smart/authorize                   the redirect to the record
  GET /smart/callback                    the code, exchanged for a session

The discovery document answers the three things the task named --
authorization_endpoint, token_endpoint and the capabilities
["launch-ehr", "client-public"] -- and the rest of what a record reads.

The client keeps no secret: a secret in a repository is a secret in
everybody's repository, so it proves that it started the flow with PKCE
instead. It sends the hash of a random verifier in the authorization
request and the verifier itself in the token request. The state carries
the verifier, so it is signed with the application's own secret, and a
state that was changed in the browser is refused.

Who may sign in is the practice's decision, not the record's: the identity
in config/smart_clients.yaml is mapped to a local account, and a
clinician with no line there is refused.

The application is a client, not an authorization server: it launches
*from* a record, and nothing in the MVP needs the other direction.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
