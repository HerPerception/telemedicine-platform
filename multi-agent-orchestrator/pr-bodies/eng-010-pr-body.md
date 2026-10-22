# ENG-010: the application refuses to start when it is not ready

Running the application by hand showed two things that should not have
been true.

The error was a raw "No module named 'psycopg'" from three frames down.
It is now a sentence that says what to do: install the project's
dependencies. The apply script and the server both report it and stop.

Worse, the server started and announced "the database" when there was no
driver and no database at all. A deployment that believes it has a database
and does not puts the records of one request in memory and the records of
the next in the database, and that fault is discovered by a patient rather
than by a monitor. The application now checks the database before it
serves: the driver has to be installed, the database has to be reachable,
and the schema has to have been applied. It refuses to start otherwise, and
says which of the three it was.

The messages are flushed as well, so they are not lost when the output is
a pipe.

The continuous integration found the ordering this needs: it applied the
schema after the suite rather than before it, so the end-to-end test
started an application against a database with no schema in it. The
workflow applies the schema first now, and a database made for a test
comes with the schema applied, so the mistake cannot be made twice.

Also: the settings and the design document now say how to install the one
dependency, and there is a test for each of these messages.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

# ENG-010: the application assembled, and the whole stack over HTTP

The application was assembled by hand: the records service, the slots, the
booking service, the prescriptions, the authentication, the video rooms and
the two HTTP surfaces. That is fine for a test and wrong for a deployment,
where the wiring has to be right and identical every time.

* telemedicine/config.py - the settings, read from the environment:
  TELEMEDICINE_DATABASE_URL, TELEMEDICINE_HOST and TELEMEDICINE_PORT. The
  default host is 127.0.0.1, because a server that listens on every
  interface by accident is a server that answers on a network it was never
  meant to, and the description of the settings never prints the connection
  string.
* telemedicine/application.py - the wiring, in one place. With a database,
  every store is the database one: the records, the audit log, the lockout
  counter, the accounts, the sessions and the prescription documents, and the
  application can run in more than one instance. Without one, the same
  services keep the records in memory, which is what the tests use. The
  audit log is shared by every service, because one trail is the only kind
  of trail that is a trail.
* scripts/run_server.py - the entry point. It does not apply the schema:
  that is a deployment step, done once, because a process that starts
  should not change the shape of the database underneath it. It warns
  loudly when it runs without a database.
* tests/test_application.py - 8 tests. The end-to-end one builds the
  application the way a deployment does, runs it over a real socket against
  a real database, and then does what a patient does: register, sign in,
  book a slot the clinician opened, read the booking back through the FHIR
  API, and be refused when they ask for somebody else's.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
