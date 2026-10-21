# TODO_LEGAL — what is waiting for a lawyer, and what to do until then

- **The practice has no legal adviser yet.** This file lists what is waiting for one, and what the
  practice should do until there is one.
- **Nothing here is a decision the software made.** Every number in it is a placeholder, and every
  one of them is marked as such where it lives.

## 1. The retention numbers — pending sign-off

**Where they are:** `config/retention_policy.yaml`.

**What they are now:** conventional practice, not law. Five years for an adult's outpatient record,
seven for an inpatient one, records made while the patient was a child kept until they reach 21, ten
years for a prescription, seven for the audit trail. The file says `TODO_LEGAL` at the top.

**Why they are placeholders.** The period for a clinical record is set by the **National Health Act
2014** ("Obligation to keep record") and by the guidance of the **Medical and Dental Council of
Nigeria**, not by the Data Protection Act. The clause could not be read from the gazette scan
available when the file was written, so **no number is asserted as law anywhere**.

**What is waiting:**

1. the adviser reads the record-keeping clause of the National Health Act 2014, and the MDCN's
   guidance on how long a practice keeps a record;
2. the adviser confirms or replaces each number;
3. the adviser signs — `legal_advisor_signed: true` in the policy file;
4. the practice decides whether to turn the mechanism on at all — `enabled: true`.

**Until then, nothing is deleted.** The job reports what is past its period and changes nothing,
and the policy is switched off in two places, so it cannot run by accident.

## 2. The cross-border justifications — pending review

**Where they are:** `config/external_services.yaml`.

**What they are now:** empty. Every service outside Nigeria — SendGrid, Mailgun, Postmark, Twilio,
Daily, LiveKit, Zoom, AWS, Firebase, OpenAI — is therefore **blocked**, and a request to send to
one is refused:

> Transfer blocked: no lawful basis recorded per NDPA s43

**Why.** Section 41(1) of the **Nigeria Data Protection Act 2023** forbids transferring personal
data from Nigeria to another country unless the recipient has an adequate level of protection or
one of the conditions in section 43 applies, and section 41(2) requires the basis to be recorded.
Section 43(a) is the patient's consent, given after being informed of the risks of the transfer.

**What is waiting:**

1. the adviser says, for each service the practice actually uses, whether a transfer to it is
   lawful and on what basis;
2. the practice records that basis and a written justification in the service's entry;
3. the transfer log (`transfer_logs`) is checked to see what has already gone where — the
   `python3 scripts/audit_external_services.py` command prints it.

**Until then, nothing leaves the country.** The mail server the practice uses has to be in Nigeria
or be in the configuration as one.

## 3. The privacy notice — pending markup

**Where it is:** `docs/compliance/privacy-notice-draft.md`.

**What it is now:** a draft. It answers all seven requirements of section 27(1) — who the controller
is, the lawful basis and the purposes, the recipients, the rights, the retention period, the right
to complain to the Commission, and the automated decision-making — and it carries the warning
**"DRAFT - pending legal advisor"**. The "How long we keep data" table is **generated from the
retention policy file**, so the notice and the job cannot drift apart.

**What is waiting:**

1. the adviser marks it up: the lawful bases, the wording of the rights, the complaints route,
   and the description of what is shared with the pharmacy, the mail provider and the video server;
2. the practice fills in the practice's own details — its name, its address, its Data Protection
   Officer, the domains, and the version number of the notice;
3. the five consents (A–E) are checked against what the practice will actually ask for, and the
   notice is versioned.

**Until then, the notice is not shown to a patient** — and the version string a client sends with a
consent is whatever the practice says it is.

## 4. The recommendation: host everything in Nigeria, and use test data

**Until the lawyer has reviewed:**

- **Host everything in Nigeria.** The application, the database, the mail server, the media server
  and the bucket the recordings go into — all of them, in the country. This is what makes the
  transfer question a question about configuration rather than a question about the product: with
  everything here, section 41 is not engaged at all, because nothing is transferred.

  Concretely: the media server is the practice's own (`webrtc-server/` — LiveKit, coturn and MinIO
  on one machine in Nigeria, not a managed service abroad); the mail server is one in Nigeria; the
  database is one in Nigeria; and the anchors the audit chain is published to are on a machine the
  application cannot write to, in the same country.

- **Use test data, not real patients.** Until the adviser has confirmed the retention numbers, the
  transfer bases and the notice, there should be no real patient data in the system at all. The
  compliance review's sign-off conditions say the same thing: no real patient data before sign-off.

- **Leave the demo mode on.** `TELEMEDICINE_DEMO_MODE` is **on by default**, and every document
  says **"DEMO - NOT FOR REAL PATIENTS"** on its face. A prescription that could be mistaken for a
  real one is worse than one that says plainly that it is not. Turn it off only when the practice
  is ready for the documents to be real.

- **Keep the two switches off.** `enabled: false` and `legal_advisor_signed: false` in the
  retention policy, and `TELEMEDICINE_SMART_FHIR_ENABLED` unset. Nothing deletes, and nothing
  launches from a hospital's record.

## What changes when the adviser has signed

| | Then |
| --- | --- |
| the retention numbers | put the confirmed numbers in `config/retention_policy.yaml`, sign them, and decide whether to switch the mechanism on |
| the transfer bases | record the basis and the justification for each service the practice uses |
| the notice | mark it up, fill in the practice's details, and version it |
| the demo mode | `TELEMEDICINE_DEMO_MODE=false`, once real records are going in |

## The short version

The software is finished enough to be honest about: the consent is captured and can be taken back
by the patient, the transfers are refused unless they are recorded, the retention mechanism is
built and switched off, the media server is the practice's own, and every document says on its face
that it is not for real patients.

**What is missing is not code.** It is a lawyer, and the five answers in the table above.
