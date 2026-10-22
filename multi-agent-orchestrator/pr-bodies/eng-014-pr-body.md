# ENG-014: the delivery worker and the mail transport

The outbox of ENG-011 queued the messages and left the sending to
somebody else. This is that somebody else.

* telemedicine/delivery.py - DeliveryWorker drains the queue, on a
  schedule, and is what a deployment runs as a sidecar or from a cron.
  SmtpTransport is the transport that talks to a mail server; the
  standard library has smtplib, so the project gains no dependency for
  it.
* scripts/run_delivery.py - the entry point. It refuses to run without a
  database, because there would be no outbox to drain, and without a mail
  server, because nothing could be sent. It says which.
* The settings for the mail server, and the password is read from the
  environment and written nowhere: not to the log, not to the audit
  trail, not to the outbox, and not into the message.
* tests/test_delivery.py - 16 tests.

Delivery is at least once: the worker sends a message and then marks it
sent, and a process that dies in between sends it again. A transport has
to be willing to send the same message twice, which a confirmation is.

A message for an account with no address fails, with the reason, and is
retried and then given up on rather than silently dropped. A failure does
not stop the other messages.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
