# ENG-012: anchor the audit chain outside the database

The chain of the audit log is only as good as the store it is in. An
attacker with write access to the audit_log table can rewrite the entries
and rebuild the chain, and the chain will verify again: a chain that was
rewritten from the beginning is still a chain. The hash detects an entry
edited in the middle; it does not detect a chain replaced wholesale.

So the head of the chain is now published outside the database.

* telemedicine/audit_anchor.py - an Anchor records the hash of an entry, its
  position in the chain, and the hash of the whole chain at that moment. An
  AuditAnchor is where those records go; the implementation is a file, one
  anchor per line, appended and never rewritten, which lives outside the
  database and can be copied off the machine. AnchoredAuditLog wraps any
  log and publishes an anchor every N entries.
* scripts/verify_audit_chain.py - what the operator runs: the chain is
  checked internally, and then against the anchors. A chain that was
  rewritten from the second entry onwards verifies internally and fails
  against the anchors.
* The setting is TELEMEDICINE_AUDIT_ANCHOR. Without it the chain is not
  anchored, and the application says so rather than pretending.
* tests/test_audit_anchor.py - 12 tests. The important one does exactly
  what an attacker would do: rewrite every entry from the second onwards
  and rebuild the chain so that it verifies again, and then checks that the
  anchor catches it.

This closes SEC-07 of the compliance review.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
