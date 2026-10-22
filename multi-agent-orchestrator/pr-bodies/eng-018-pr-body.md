# ENG-018: the gate on transfers out of Nigeria

Section 41(1) of the Nigeria Data Protection Act 2023 forbids transferring
personal data from Nigeria to another country unless the recipient has an
adequate level of protection or one of the conditions in section 43
applies, and section 41(2) requires the basis for the transfer to be
recorded. Section 43(a) is the patient's consent, given after being informed
of the risks of the transfer.

So a transfer out of Nigeria needs three things before anything is sent:

  1. a known destination -- the configuration says where each service is,
     and one that is not listed cannot be shown to be in Nigeria;
  2. a lawful basis -- consent, contract, vital interest, public interest
     or legal claim;
  3. a written justification -- what the transfer is for, in the practice's
     own words.

Without the basis: "Transfer blocked: no lawful basis recorded per NDPA
s43". Without the justification: "Transfer blocked: no justification
recorded per NDPA s41(2)". A service in Nigeria needs neither: nothing
leaves the country.

The configuration is the source of truth. config/external_services.yaml
lists each service, its country, and the basis and justification recorded
for it -- and every service outside Nigeria ships with an empty
justification, so **every transfer out of Nigeria is refused until the
practice fills one in**. That is a decision the practice has not been able
to make yet, and should not have to make in order to build the system.

The gate is called before the connection, not after it. The mail transport
asks it before it opens an SMTP connection, so a refused transfer means no
connection was made at all. The same guard is on the application, so the
media transport when there is one asks the same question the same way.

The country is checked twice: the configuration is authoritative, and a
caller that says the destination is in Nigeria while the configuration says
the service is in the United States is refused. One of the two is wrong,
and the safe answer is to refuse.

A transfer that happens is written to transfer_logs: when, which service,
which host, which country, which recipient, what kinds of data, the basis,
the justification, and whose data it was. The table is append-only. A
refused transfer is not logged, because there is nothing to record about
something that did not happen.

python3 scripts/audit_external_services.py lists every service, its
country, whether it is blocked and why, the basis and justification
recorded for it, whether it is configured in this project, and whether
anything has been sent to it. A blocked service is not a failure: the
expected state until the practice confirms the numbers must not look like a
broken command.

The configuration is read strictly, by a small hand-written reader that
the retention policy now shares: an unknown key, a missing key, a value of
the wrong type or a line that is not a key and a value is an error, not
something quietly ignored.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
