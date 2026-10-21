# The gate on transfers out of Nigeria

- **Feature:** ENG-018 — the cross-border transfer gate, and the log of transfers
- **Why it exists:** section 41(1) of the Nigeria Data Protection Act 2023 forbids transferring
  personal data from Nigeria to another country unless the recipient has an adequate level of
  protection or one of the conditions in section 43 applies. Section 41(2) requires the basis to
  be recorded. **Section 43(a) is the patient's consent**, given after being informed of the risks
  of the transfer.
- **What it does:** refuses the transfer, and records the ones that happen.

## The rule

A transfer out of Nigeria needs **three** things before anything is sent:

1. **A known destination.** The configuration says where each service is. A destination that is not
   in the configuration is refused: it cannot be shown to be in Nigeria, and showing it is the whole
   point.
2. **A lawful basis** — `consent`, `contract`, `vital_interest`, `public_interest` or
   `legal_claim`. Without one: *"Transfer blocked: no lawful basis recorded per NDPA s43"*.
3. **A written justification** — what the transfer is for, in the practice's own words. Without
   one: *"Transfer blocked: no justification recorded per NDPA s41(2)"*.

A service **in Nigeria** needs none of the three: nothing leaves the country.

**The configuration is the source of truth.** `config/external_services.yaml` lists each service,
the country it is in, and the basis and justification the practice has recorded for it. The shipped
file has an empty justification for every service outside Nigeria, so **every transfer out of
Nigeria is refused until the practice fills one in** — which is a decision the practice has not been
able to make yet, and should not have to make in order to build the system.

The example the practice would fill in:

```yaml
sendgrid.lawful_basis: consent
sendgrid.justification: Patient consented to email receipts, see consent ID
```

## Where it sits

**The gate is called before the connection, not after it.** The mail transport asks the guard
before it opens an SMTP connection, so a refused transfer means no connection was made at all:

```python
self.guard.permit(
    TransferRequest(
        destination_country="",
        recipient=address,
        data_categories=[notification.kind],
        lawful_basis=self.lawful_basis,
        justification_text=self.justification,
    ),
    host=self.host, service="smtp", user_id=notification.recipient_user_id)
```

The same guard is on the application (`application.transfer_guard`), so any outbound path — the
media transport when there is one — asks the same question the same way.

**The country is checked twice.** The configuration is authoritative, and if the caller says the
destination is in Nigeria while the configuration says the service is in the United States, the
request is refused: one of the two is wrong, and the safe answer is to refuse.

## The log

A transfer that happened is written to `transfer_logs`: when, which service, which host, which
country, which recipient, what kinds of data, the basis, the justification, and whose data it was.
The table is **append-only** — the schema refuses a change to a row, its removal and its truncation
— because a transfer that could be edited afterwards would not be a record of the transfer.

**A refused transfer is not logged.** There is nothing to record about something that did not happen.

The log can be pruned safely, unlike the audit trail: it is not a hash chain. The retention job
does not touch it yet.

## The inventory

```bash
python3 scripts/audit_external_services.py
```

It lists every service, its host, its country, whether it is blocked and why, the basis and
justification recorded for it, whether the service is configured in this project (from `.env` and
from `package.json`), and whether anything has been sent to it.

**A blocked service is not a failure.** The command exits 0 and says so: the expected state until
the practice confirms the numbers must not look like a broken command.

## Where it is applied, and where it is not

| Path | Guarded? |
| --- | --- |
| the mail transport (`telemedicine/delivery.py`) | **yes** — the guard is called before the connection |
| the media transport | not built yet; the guard is on the application for it to use |
| the database | never leaves the machine |

**The database is not guarded and does not need to be**: it is where the records are, and a
deployment that put it outside Nigeria would be a deployment that had already broken section 41
before any code ran.

## What is not built

- **A country lookup from an IP address.** There is no IP-to-country database in the project, and
  there will not be one: the configuration is the source of truth, and an unknown destination is
  refused rather than guessed at.
- **A check that the destination's country is still what the configuration says.** The
  configuration is updated by hand, and the review of it is a practice matter.
- **A way to see the refusals.** They are refused and nothing is logged, because a refusal is not a
  transfer. The count of refused attempts would be useful, and is not here.
