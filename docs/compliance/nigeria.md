# The Nigerian answer

- **Feature:** OPS-003 — the compliance answers for the practice's jurisdiction
- **Status:** answered, with the law read from the official texts on 2026-10-20. The consent machinery and the breach report are built. Four things still need a Nigerian adviser, and they are named in §12.
- **Owner:** `OpenCode-20261020-3dafd2c8`

## 1. The short answers

The practice answered four questions on 2026-10-20, and asked to be advised on two of them. Here is the
advice, in the order of the questions.

| Question | Answer |
| --- | --- |
| **Where is the practice, and where are the patients?** | **Nigeria.** Everything below follows from that. |
| **Which drug code system?** | There is no national medication terminology in force yet, so: **code the medicine internationally, identify it locally.** Put an RxNorm concept on the prescription for safety checking, and the **brand name and NAFDAC number** on it for dispensing. §6. |
| **What do patients agree to?** | **Not one form.** The clinical record does not need consent at all — the law gives it its own ground. The optional uses each need their own consent, and each can be withdrawn on its own. §3. |
| **How long are records kept?** | The law requires the practice to **state** a period. The clinical period comes from the National Health Act 2014 and the Medical and Dental Council; a draft table is in §5, and until it is confirmed the system deletes nothing. §5. |
| **Which video provider?** | **One you run yourselves, in Nigeria.** A provider's servers outside Nigeria are a transfer of personal data out of Nigeria, which the law restricts. §7. |

## 2. The law

The sources are the official texts, read on 2026-10-20:

| Law | Where it came from | Used for |
| --- | --- | --- |
| **Nigeria Data Protection Act 2023** | the copy published by the Commission itself: `ndpc.gov.ng/wp-content/uploads/2024/03/Nigeria_Data_Protection_Act_2023.pdf` (43 pages) | consent, security, breach, transfers, registration |
| **Nigeria Data Protection Commission** | `ndpc.gov.ng` — the Commission's own description of the Act's parts | the rights (sections 34–38), the registration and audit filing, the breach reporting service |
| **National Health Act 2014** | the gazette copy: `faolex.fao.org/docs/pdf/nig162642.pdf` | the medicines list, the obligation to keep records, access to and protection of health records |
| **Nigeria Core FHIR Implementation Guide** | the National Digital Health Initiative's own repository: `github.com/digitalhealth-gov-ng/Nigeria-Core` | the national direction for FHIR, which this project already follows |

Two things are worth saying about these sources. The Act and the National Health Act are law; the
Nigeria Core guide is a national direction for digital health, built by the Federal Ministry of
Health, and it is marked "work in progress" where it is quoted below. Where a document is not yet
binding, that is said.

The parts of the Act that matter to this project, in the words of the Act:

- **Section 30(1)** — sensitive personal data, which includes health status, may not be processed
  unless one of the listed grounds applies.
- **Section 30(1)(a)** — the ground of consent, for "the specific purpose or purposes for which it
  will be processed".
- **Section 30(1)(g)** — "processing is carried out for purposes of **medical care or community
  welfare**, and undertaken by or under the responsibility of a professional or similar service
  provider owing a duty of confidentiality".
- **Section 27** — before collecting data, the controller must tell the data subject the lawful
  basis and the purposes, the recipients, the rights under Part VI, the **retention period**, the
  right to complain to the Commission, and any automated decision-making.
- **Section 32** — a data controller of major importance must designate a Data Protection Officer.
- **Section 35** — "A data subject shall have the right to withdraw, at any time, consent", and
  "the data controller shall ensure that it is as easy for the data subject to withdraw, as to give
  consent".
- **Section 39** — technical and organisational measures for the security, integrity and
  confidentiality of personal data, taking account of the sensitivity of the data and the retention
  period.
- **Section 40(2)** — "A data controller shall, **within 72 hours** of becoming aware of a breach
  which is likely to result in a risk to the rights and freedoms of individuals, notify the
  Commission", describing the nature of it, "including the categories and approximate numbers of
  data subjects and personal data records concerned". Section 40(3): a breach likely to result in a
  **high risk** to a data subject must be communicated to that data subject immediately.
- **Sections 41–43** — personal data may not be transferred from Nigeria to another country unless
  the recipient is adequately protected (section 42) or a section 43 condition applies, and **the
  basis for the transfer must be recorded** (section 41(2)).
- **Section 44** — a data controller of major importance must register with the Commission, and the
  registration names, among other things, the Data Protection Officer, the purposes, the recipients,
  the countries to which data will be transferred, the risks and the security measures.

## 3. Consent: why it is not one form

The practice asked for "one form covering everything". The law points to a different shape, and the
reason is worth stating plainly, because it is the difference between a form that is right and a form
that only looks right.

**The clinical record does not rest on consent.** Section 30(1)(g) allows a practice to process a
patient's health data for medical care, under the responsibility of a professional owing a duty of
confidentiality. A practice treating a patient is doing exactly that. So the consultation, the
diagnosis, the prescription and the notes are made under section 30(1)(g) — not because the patient
signed anything. The patient is **told** about it, through the section 27 notice.

**Consent is for everything else.** Research, teaching, marketing, sharing with another provider:
each of these needs its own consent, given for the specific purpose (section 30(1)(a)), and each can
be withdrawn on its own (section 35).

If everything were bundled into one signature, three things would go wrong:

1. the care record would be made to look as though it rests on consent, when it does not — and a
   patient who withdrew the form would be withdrawing the basis of their own treatment;
2. the optional uses would be unwithdrawable in practice, because withdrawing one of them means
   withdrawing the signature on the form that also carries the care consent;
3. section 30(1)(a) requires consent "for the specific purpose" — one form for four purposes is not
   consent to a specific purpose.

So the design is **two things, kept apart**:

- **the notice** — what the patient must be told before their data is collected. Recording that it
  was shown is an *acknowledgement*, not a consent, and the software keeps it in a different field
  from any consent, so the two can never be confused.
- **the consents** — one per optional purpose, each grantable, each withdrawable, each tied to the
  version of the notice the patient actually saw.

**What the software now does.** `telemedicine/consent.py` holds the machinery:

- `ConsentService.grant(user, purpose, notice_version)` — records a consent for one optional use;
- `ConsentService.withdraw(user, purpose)` — withdraws it, at once, without touching the others;
- `ConsentService.acknowledge_notice(user, notice_version)` — records that the notice was shown;
- `ConsentService.has_consent(user, purpose)` — the question "may we do this?";
- `ConsentService.history(user)` — everything that happened, in order.

The record is **append-only**, like the audit log: a withdrawal is a new row, not a change to the
old one, so what the patient agreed to and when they stopped agreeing to it can both be shown. The
table is `consent_event` (`db/consent_schema.sql`), and the database refuses an update, a delete and
a truncate on it.

**What it does over HTTP.** ENG-015 put the service behind an API: `GET /fhir/consent` for the
patient's own state, `POST /fhir/consent/<purpose>` to grant, `DELETE /fhir/consent/<purpose>` to
withdraw, and `POST /fhir/consent/notice` for the acknowledgement. A clinician who treats the
patient may read the state — they have to know before they use a record for a research purpose — and
may change nothing. The endpoints are in `docs/consent-design.md`.

So the withdrawal is one request, which is what section 35 asks for: it has to be "as easy for the
data subject to withdraw, as to give consent".

The draft wording for both the notice and the optional-use consents is in
`docs/compliance/privacy-notice-draft.md`. **It is a draft, and it is marked as one**: it is
wording for the practice's adviser to mark up, not wording to use.

## 4. What the notice has to contain

Section 27(1) sets out what the patient must be told before their data is collected. The draft
notice has all seven, and the draft records which section each one answers:

| Section 27(1) | What must be said | Where it is in the draft |
| --- | --- | --- |
| (a) | who the controller is and how to reach it | §1 |
| (b) | the lawful basis and the purposes | §2 |
| (c) | the recipients or categories of recipients | §3 |
| (d) | the rights under Part VI | §6 |
| (e) | the retention period | §5 |
| (f) | the right to complain to the Commission | §7 |
| (g) | any automated decision-making | §4 (there is none) |

The rights under Part VI, from the Commission's own description of the Act: to be informed, to
access, to have inaccurate data rectified, to object to processing, to report to the Commission, to
have processing restricted, to data portability, to be forgotten, and not to be subjected to
automated decision-making (sections 34–38).

## 5. Retention

**What the law requires.** Section 27(1)(e) requires the notice to state the retention period.
Section 39(1)(d) requires the security measures to take account of the period of retention. The
National Health Act 2014 has a section headed "Obligation to keep record", and sections headed
"Access to health records" and "Protection of health records". **The retention period itself is not
in the Data Protection Act** — it is health-sector law, and it is a question for the National Health
Act and for the Medical and Dental Council of Nigeria.

**What could not be read here.** The gazette PDF of the National Health Act 2014 is a scan whose
text does not extract cleanly; the section headings and the section on the Essential Drugs List
(section 39) came through, but the operative clause of the record-keeping section did not. So the
**period is not stated from the Act here**, and this document does not pretend otherwise: the clause
has to be read by someone with a clean copy, and the practice's adviser has to confirm it.

**The draft policy**, to be confirmed and then filled in. The practice's adviser sets the numbers;
this is the shape.

| Record | Period | Why |
| --- | --- | --- |
| Consultation records, notes, diagnoses | **to be confirmed** — the National Health Act 2014 and MDCN guidance | health-sector law, not the Data Protection Act |
| Prescriptions and the documents issued | **to be confirmed** — normally the same as the consultation record | |
| Appointment records | **to be confirmed** — normally a shorter period than the clinical record | |
| The audit trail | **to be confirmed** — usually the longest, because it is the evidence | |
| Consent records | **to be confirmed** — kept at least as long as the record they cover | |
| Failed sign-in attempts and lockouts | a short, fixed period — the practice sets it | security, not clinical |

**Until those numbers are confirmed, the system deletes nothing.** That is deliberate: deleting on a
guess is irreversible, and keeping too long is a smaller harm that can be fixed later. What the
system cannot yet do is *apply* a period — there is no deletion job, and there is no "deleted"
marker. §13.

## 6. Medicines: which code system

**The statutory list.** Section 39 of the National Health Act 2014: "There shall be a compendium of
drugs approved for use in health facilities throughout the Federation (in this Act referred to as the
'**Essential Drugs List**') which shall be under the periodic review of the National Drugs Formulary,
and Essential Drugs Formulary Review Committee."

**But there is no national medication *terminology* yet.** The Nigeria Core FHIR Implementation
Guide — the national direction from the Federal Ministry of Health, built by the National Digital
Health Initiative — states that the national terminology service will provide "Nigerian local codes
and mappings to international terminologies such as ICD-11, SNOMED CT, LOINC, ATC", and the
terminology server itself is not yet in place. The guide is at "work in progress" stage, and its
security page already expects OAuth 2.0 and SMART-on-FHIR tokens, which this project does not have
yet (a known gap, SEC-08).

**So the answer is to carry both things.** A prescription has to be *coded* so that interactions and
allergies can be checked, and it has to be *dispensable* in a Nigerian pharmacy:

| On the prescription | Why |
| --- | --- |
| a coded concept — RxNorm, with SNOMED CT or ATC alongside | the check for interactions and duplicate therapy needs a code that means one thing everywhere; RxNorm is the medication terminology the international ecosystem already uses, and it is the safest of the candidates for a local code that does not exist yet |
| the **brand name** and the **NAFDAC registration number** | what the pharmacy actually dispenses; without it a prescription with an invented code cannot be dispensed |
| the dose, the route and the duration, in plain words | the prescriber's words, not the code's |

**What the software does now.** ENG-005 issues the prescription document; it carries the medication
coded and the dose in plain text. **It does not yet carry the brand or the NAFDAC number** — that is
a change to the prescription document and to the FHIR mapping, and it is in §13.

The one thing that must not happen: a prescription that names a medicine the Essential Drugs List
does not carry should be a decision a prescriber makes knowingly, not an accident of a code that
does not resolve. A code that cannot be resolved must be visible as unresolvable, not silently
displayed.

## 7. The video provider

The question was "advise me on the privacy trade-off". The law answers most of it.

**Section 41(1):** "A data controller or data processor shall not transfer or permit personal data
to be transferred from Nigeria to another country, unless (a) the recipient ... is subject to a law,
binding corporate rules, contractual clauses, code of conduct, or certification mechanism that
affords an adequate level of protection ... or (b) one of the conditions set out in section 43
applies." Section 41(2): the basis for the transfer **must be recorded**.

A video consultation carries the patient's picture and voice. If the media server is outside Nigeria,
that is a transfer of personal data out of Nigeria. Section 42(1) asks whether the recipient's
protection is "substantially similar" to the Act's — and section 42(2) sets out how that is
assessed: enforceable rights and redress, an instrument between the Commission and the foreign
authority, and what a foreign public authority can do.

**So, in order of preference:**

1. **A server you run, in Nigeria.** No transfer, so none of section 41 applies; no vendor holds
   the media; no vendor can change the terms. This is the default this project should take.
2. **A managed provider with servers in Nigeria.** Check where the media actually goes, not where
   the company is registered, and get the answer in writing.
3. **A managed provider outside Nigeria.** This is lawful only with an adequacy basis under section
   42 or a section 43 ground — section 43(a) is the patient's consent to the transfer "after having
   been informed of the possible risks", which is a poor thing to ask of a sick patient at the moment
   of booking. **And the basis has to be recorded**, and the country of transfer has to be named in
   the Commission's registration (section 44).

**What that means for the build.** ENG-004 has the rules — who may join, when, the waiting room, the
tokens — but no transport. The transport should therefore be written as an interface with **one
implementation**: a media server you run. That is a small amount of extra work now, and it is the
difference between a lawful and an unlawful configuration later.

**And the section 43 question has to be recorded wherever the practice does use a provider.** The
system should have a place to record it — the answer to "what is the basis for the transfer?" — and
it does not have one yet (§13).

## 8. The 72-hour breach report

Section 40(2) is a duty with a clock on it, so the system has to be able to produce the report
quickly. `scripts/report_breach.py` assembles the half of the report that is a matter of fact, from
the audit log the project already keeps:

- the window, and how many access events fell in it;
- the **categories and approximate numbers of data subjects** and of personal data records concerned
  — the words section 40(2) uses;
- what was done with them, by action;
- the records the controller believes were affected, if given.

It deliberately does **not** write the likely consequences, or the measures taken or proposed: those
are judgments, and a report that looks finished when it is not is worse than one that admits what is
missing. The report says so on its face, and it says that a high-risk breach must be told to the
data subject immediately (section 40(3)).

The decision to notify the Commission is the controller's, and the notification itself goes through
the Commission's own channel. The script is a drafting aid.

## 9. The registration

Section 44 requires a data controller of major importance to register with the Commission, and to
file audit compliance returns. A practice that runs a telemedicine service with patient records is
very likely to be a controller of major importance — the Commission's own register is the place to
confirm, and the threshold is the Commission's to apply.

What the registration must contain, and what the practice has to decide for each item:

| Section 44 requires | What the practice has to supply | Status |
| --- | --- | --- |
| the name of the Data Protection Officer | a person — section 32 requires one with expert knowledge of data protection law, who may be an employee or engaged by contract | **the practice's decision** |
| the data and the purposes of the processing | the clinical record, the appointments, the prescriptions, the audit trail, the account data | answered by this document |
| the recipients or categories of recipient | the practitioners, the pharmacy for prescriptions, the mail provider for messages, the video provider | **depends on §7** |
| the **country to which data will be transferred** | none, if the media server is in Nigeria | **depends on §7** |
| the risks | the consequences of a breach of health data | §8 |
| the safeguards | the security measures of section 39 | the review, in `docs/reviews/` |
| the security measures | encryption at rest and in transit, the audit trail, the lockout, the access control | the review, in `docs/reviews/` |

The registration has to be filed within six months of becoming a controller of major importance
(section 44). The Commission's own contact for it is `info@ndpc.gov.ng`.

## 10. The Data Protection Officer

Section 32 requires a designated Data Protection Officer for a controller of major importance, with
expert knowledge of data protection law, who may be an employee or engaged by contract. The DPO
advises the controller and its staff, monitors compliance, and is the Commission's contact point
(section 32(3)).

**This is a person, not a feature.** It is the practice's decision, and it is a real cost. The
system's part is to make the DPO's job possible: the audit trail, the consent record and the breach
report are exactly the things a DPO is asked about.

## 11. What the practice must do, and by when

| | Who | By when |
| --- | --- | --- |
| Appoint the Data Protection Officer | the practice | before the service takes a real patient |
| Confirm the retention periods with the National Health Act 2014 and MDCN | the practice and its adviser | before the service takes a real patient |
| Mark up the privacy notice and the optional-use consents | the practice and its adviser | before the notice is shown to anyone |
| Decide the video provider, and record the transfer basis if there is one | the practice | before the first video consultation |
| Register with the Commission as a controller of major importance | the practice | within six months of becoming one |
| Read the retention clause of the National Health Act 2014 from a clean copy | the adviser | with the retention question |
| Work out whether a controller of major importance means this practice, and what it entails | the adviser | with the registration |
| Set up a process for the 72-hour breach report, and for telling a patient immediately in a high-risk breach | the practice | before the service takes a real patient |

## 12. What is still not settled

1. **The retention periods.** The requirement is certain; the numbers are not, and the clause could
   not be read from the scan available here. §5.
2. **The wording of the notice and of the consents.** The draft is a starting point, not an answer.
3. **Whether this practice is a controller of major importance**, and what that entails. The
   threshold is the Commission's to apply.
4. **What the section 43 basis would be**, if the practice chooses a provider outside Nigeria. §7.
5. **The court and the regulator for complaints** — the notice must name the right body for the
   practice's own state, which is a question of local practice, not of law.

None of these is an engineering problem. They are four questions for the practice and its adviser,
and they are the last of the compliance review's blockers.

## 13. What the software still has to do

The engineering work that follows from this document, in the order it should be done:

1. ~~**Expose the consent service over HTTP**~~ — **done (ENG-015)**: the patient can see and
   withdraw, and a clinician who treats them can see the state before an optional use. The notice
   acknowledgement is an explicit act rather than part of registration, because there is no HTTP
   sign-up to attach it to. `docs/consent-design.md`.
2. **Carry the brand name and the NAFDAC number** on the prescription document and in the FHIR
   mapping (§6).
3. **Apply the retention policy** — the deletion job, the "deleted" marker, and the audit entry for
   each deletion, once the periods are confirmed (§5).
4. **A place to record the basis for a transfer**, and to refuse a transfer with no basis (§7).
5. **The media transport**, written as an interface with one implementation: a server the practice
   runs (§7).
6. **OAuth 2.0 and SMART-on-FHIR**, which the Nigeria Core guide expects and this project does not
   yet have (SEC-08).
7. **The audit trail exported for the DPO** — the trail is there; the report is not.

Items 3 and 4 are the ones the law puts a clock on. Item 1 was the third, and ENG-015 did it.
