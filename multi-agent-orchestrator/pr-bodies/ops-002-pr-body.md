# OPS-002 (pre-work): the container, the settings and the runbook

The parts of a deployment that live in the repository, so that the
deployment itself is a matter of filling in a host and a certificate.

* Dockerfile - one image, two jobs: the API and the delivery worker, chosen
  by the container's command, so they always have the same code and the same
  settings. It runs as a user that is not root, it holds no tests and no
  compiler tools, and the package and its one dependency are installed
  before the rest of the code, so a change to the code does not reinstall
  them.
* docker-compose.yml - a staging environment: the API, the delivery worker
  and a database. The database is not published to the host; only the
  application talks to it. The audit anchors are on a volume, so they
  survive a restart.
* scripts/healthcheck.py - is the application ready to serve? It asks
  whether the server answers and whether the database is there with the
  schema, and prints what it found, because a health check that says only
  "unhealthy" costs an hour. The container's HEALTHCHECK runs it.
* docs/deployment.md - the runbook: what a deployment is, every setting it
  needs and what happens without it, how to bring it up, how to know it is
  working, how to check the audit chain, the anchors and the backups, how to
  upgrade, and the four questions the practice still has to answer before a
  real patient is in there.
* .env.example - the settings, with the passwords left blank.
* tests/test_deployment.py - the pieces have to agree with each other and
  with the code. The test caught a compose file naming settings the code
  did not read, because the mail server's settings were still on an
  unmerged branch.

The image has not been built: Docker is not available to this user. The
compose file was parsed, and the artefacts were checked against the code.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
