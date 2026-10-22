# ENG-013: sign in over HTTP, and a lockout that counts the address

There was no way to sign in over HTTP. The authentication service existed
and the API had no endpoint that reached it, so a client had no way of
getting a token, and the whole API was usable by nothing but the tests.

* POST /fhir/session and POST /video/session sign in and return a
  token; DELETE on the same paths signs out. The endpoints are shared by
  both surfaces, so a client signs in once and uses the token for both.
  The token is in the body of a response that is not cacheable.

* The lockout now counts the address the request came from as well as
  the account, and the policy follows from the difference between them.
  An address is blocked after five failures: that is what a
  password-guessing attack from one place meets. The account is locked
  only when the failures are spread over twenty different addresses:
  that is the shape of a distributed attack, and not the shape an
  attacker with one address can produce.

  The second half is the point. An account locked after five failures
  could be locked out by one attacker who knows the address, and a
  patient who then cannot see their own results. The account counter
  grows once per address, so one address cannot do it, and a spray
  across twenty addresses is loud in the audit log.

* The address comes from the socket, and from X-Forwarded-For only when
  TELEMEDICINE_TRUST_FORWARDED_FOR says so - the header is set by
  whoever sends the request, so it is only safe behind a proxy that
  replaces it.

* The three tests of the lockout in ENG-007 follow the new policy.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
