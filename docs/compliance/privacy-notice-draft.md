# The privacy notice and the consents — DRAFT

> **This is a draft for the practice and its adviser to mark up. It is not wording to use.**
> Every `[square bracket]` is something the practice has to fill in. Nothing here has been reviewed
> by a lawyer, and the review is not optional: the notice is what the practice tells every patient,
> and the consents are the only lawful ground for the optional uses.
>
> **How it is shaped, and why.** The care record does not rest on consent: it is made under
> section 30(1)(g) of the Nigeria Data Protection Act 2023, because it is medical care carried out
> under the responsibility of a professional owing a duty of confidentiality. The patient is told
> about it here. The optional uses — research, teaching, marketing, sharing with another provider —
> each have their own consent, each for its own specific purpose, each withdrawable on its own.
> One signature for all of it would make the optional uses unwithdrawable in practice, which
> section 35 does not allow. See `docs/compliance/nigeria.md` §3.
>
> The consent model the software implements: `telemedicine/consent.py`.

---

# Part one — the privacy notice

**What the practice tells a patient before their data is collected.** Section 27(1) of the Act sets
out what must be told; the headings below mark which paragraph answers which.

## 1. Who is responsible for your data, and how to reach us

*(Section 27(1)(a))*

The data controller is **[the full legal name of the practice]**, of **[the address of the
practice]**. We can be reached at **[the telephone number]** and **[the email address]**.

Our Data Protection Officer is **[name]**, and can be reached at **[their email address]** and
**[their telephone number]**. You may contact the Data Protection Officer about anything in this
notice, or about your rights in section 6.

## 2. Why we process your data, and on what basis

*(Section 27(1)(b))*

We process your personal data for these purposes:

| Purpose | Lawful basis |
| --- | --- |
| Providing your care: the consultation, your clinical record, your prescriptions | **Section 30(1)(g)** — medical care, carried out under the responsibility of a professional owing a duty of confidentiality |
| Arranging and running your appointments | **Section 30(1)(g)**, and section 25's lawful bases for the administrative record |
| Keeping the audit trail of who did what to your record | **Section 25(1)** — the accountability of the practice for the care it gives |
| Sending you a message about an appointment or a prescription | **Section 25(1)** — the performance of a contract with you, and your request |
| Security: knowing who tried to sign in to your account | **Section 25(1)** — the security of the service and of your account |

Your health information is **sensitive personal data** under the Act. It is treated with the
safeguards the Act requires.

We do not use your health information for any other purpose unless you have agreed to that purpose
specially. The purposes you can agree to are in part two.

## 3. Who else sees your data

*(Section 27(1)(c))*

| Who | What they see | Why |
| --- | --- | --- |
| The practitioners and staff of this practice | Your clinical record | To give you care |
| **[your pharmacy or dispensary, where you choose to send a prescription]** | The prescription and your name and date of birth | To dispense it to you |
| **[your email provider]** | Your name and email address, and the content of the message | To send it to you |
| **[your video provider, if you use video consultations]** | **[what it sees — see part three]** | To hold the consultation |
| The Nigeria Data Protection Commission | **[only where the law requires it]** | The Commission's functions under the Act |
| Nobody else | — | We do not sell your data, and we do not share it for advertising |

## 4. Decisions made automatically

*(Section 27(1)(g))*

**[If there are none: "No decision about your care, or about you, is made automatically. Nothing in
this service decides anything about you without a person looking at it."]**

**[If there are any — for example a system that automatically refuses a booking, or prioritises a
waiting room: describe it, say what it decides, and say how it could affect you and how to contest
it. Do not leave this blank if the service does anything of the kind.]**

## 5. How long we keep your data

*(Section 27(1)(e))*

> **DRAFT - pending legal advisor.** The numbers below are conventional practice, not law. They are the
> placeholders the system runs on while the practice waits for a qualified adviser, and they
> change when the adviser confirms them.

| Record | How long we keep it | Where the number comes from |
| --- | --- | --- |
| clinical record | 5 years after the last visit (or until the patient reaches 21, if they were a child) | conventional practice, not yet confirmed by an adviser |
| prescription document | 10 years after it was issued | conventional practice, not yet confirmed by an adviser |
| audit log | 7 years after the entry was written | conventional practice, not yet confirmed by an adviser |

**[Until these periods are confirmed, nothing is deleted — and the mechanism that would delete
anything is switched off in two places, so it cannot run by accident. When the periods are
confirmed, this table will be regenerated from the policy file, and this notice will say what
changed and when.]**

Your consent decisions are kept at least as long as the record they relate to, and records of
failed sign-in attempts are kept for a short, fixed period — the practice sets that one.

## 6. Your rights

*(Section 27(1)(d) — Part VI of the Act)*

You have the right to:

- **be informed** about how your data is used;
- **access** your personal data;
- **rectify** data that is wrong or incomplete;
- **object** to processing;
- **restrict** processing;
- **port** your data to another provider, where the conditions in the Act are met;
- **be forgotten**, where the conditions in the Act are met;
- **not be subject to automated decision-making**, where the conditions in the Act are met;
- **withdraw a consent** you have given, at any time, and it is as easy to withdraw as it was to give
  — and withdrawing does not affect the lawfulness of the processing before you withdrew it.

Write to the Data Protection Officer, or ask at reception. We will answer within **[the period the
practice has set, and which must be lawful]**.

**[Where the Act makes a right subject to an exception, say so here plainly — for example, that a
clinical record is kept even if you ask for it to be deleted, because the practice is required to keep
it. A notice that promises more than the law allows is a broken promise.]**

## 7. If you are unhappy, you can complain to the Commission

*(Section 27(1)(f))*

If you think we have handled your data wrongly, tell us first — write to the Data Protection Officer
at **[address]**. If you are still unhappy, you may complain to the **Nigeria Data Protection
Commission**:

- Website: `ndpc.gov.ng`
- Email: `info@ndpc.gov.ng`
- Telephone: **+234 (0) 916 061 5551**
- Address: **1919 Cadastral Zone C06 Mbora District, Opposite Efab City Estate, Life Camp, FCT
  Abuja**

**[Add the practice's own internal complaints procedure and the state's health complaints body, if
the practice has one. A patient should not have to know which body is which.]**

## 8. Changes to this notice

The version of this notice is recorded against your consent decisions, so that we can always show you
the words you actually read. If this notice changes, the new version is published at **[where]** and
the date of the change is stated at the top. **[Say what happens to consents given under an older
version — for example that they continue until they are withdrawn, or that a change affecting an
optional use will be put to you again.]**

---

# Part two — the optional uses

**Four separate agreements, not one form.** Each is for one purpose, as section 30(1)(a) requires.
You can say yes to one and no to another, and you can withdraw any of them later without affecting
the others or your care.

**[Use one form for each. Each must: name the purpose in plain words; say that declining costs the
patient nothing; say how to withdraw; and be signed and dated, with a copy given to the patient.]**

## Consent A — research

> I agree that **[the legal name of the practice]** may use my health information, with my name,
> date of birth, address and any other identifying detail removed, for research into **[the areas of
> research the practice has named]**.
>
> I understand that:
> - I do not have to agree to this, and my care will not be affected if I do not;
> - my information will be used with **[the safeguards: who does the research, where it is published,
>   that it is not sold and not used to identify me]**;
> - I can withdraw this at any time, by **[how]**, and it is as easy to withdraw as it was to give;
> - withdrawing stops any further use from the date I withdraw, but it does not undo research that has
>   already been carried out.
>
> Name: ______________________  Signature: ______________________  Date: ____________

## Consent B — teaching

> I agree that **[the legal name of the practice]** may use my health information, with identifying
> details removed, to teach **[students, trainees, at which institution or to whom]**.
>
> I understand that:
> - I do not have to agree to this, and my care will not be affected if I do not;
> - **[the safeguards: the audience, whether the records are anonymised, whether they are published]**
> - I can withdraw this at any time, by **[how]**;
> - withdrawing stops any further use from the date I withdraw.
>
> Name: ______________________  Signature: ______________________  Date: ____________

## Consent C — marketing

> I agree that **[the legal name of the practice]** may contact me about **[the practice's services,
> health information, or offers]** by **[email, SMS, post]**.
>
> I understand that:
> - I do not have to agree to this, and my care will not be affected if I do not;
> - I can stop these messages at any time, by **[how]** — every message will say how;
> - my details will be passed to **[the mailing provider, if any]** for this purpose only.
>
> Name: ______________________  Signature: ______________________  Date: ____________

## Consent D — sharing with another provider

> I agree that **[the legal name of the practice]** may share my health information with
> **[the other practice, provider or service]** for the purpose of **[the purpose, stated
> specifically]**.
>
> I understand that:
> - I do not have to agree to this, and my care will not be affected if I do not;
> - the other provider will receive **[what exactly: the whole record, the prescriptions only, a
>   summary]**, and they are **[a controller of their own / a processor for this purpose]**;
> - I can withdraw this at any time, by **[how]**, and future sharing will stop. **[Say plainly what
>   happens to information already shared — it cannot be recalled from the other provider, and the
>   patient is entitled to know that.]**
>
> Name: ______________________  Signature: ______________________  Date: ____________

---

# Part three — the video consultation

**[Only if a video provider other than the practice's own server is used. If the media server is run
by the practice in Nigeria, this part is: "Your consultation is held on a server that this practice
runs, in Nigeria. No other company carries your picture or your voice."]**

> If you have a video consultation, the consultation is carried on **[the provider's full legal
> name]**'s service.
>
> - The provider's servers are in **[the country]**. **[If the country is not Nigeria, this is a
>   transfer of your personal data out of Nigeria, and the practice must have a lawful basis for it
>   under section 41 of the Act, and a record of that basis — ask us for it.]**
> - The provider sees **[the picture and the sound of the consultation]** for the length of the call.
> - The provider keeps **[what, and for how long — if the answer is that it keeps nothing, say so
>   and say how you know]**.
> - The provider does not **[use it for anything else / train models on it / sell it]** —
>   **[state the truth, and check it against the provider's contract, not its marketing.]**
> - The consultation is encrypted in transit. **[If it is not encrypted end to end, say so. Do not
>   claim a protection the service does not have.]**

**[Sign here only if the transfer leaves Nigeria and the patient is asked to consent to it under
section 43(a) — which is a weak place to ask a sick patient for consent, and a reason to run the
server yourself.]**

---

## What the practice still has to do to this document

1. Fill in every `[bracket]`, and delete the ones that do not apply.
2. Have the adviser mark it up — especially the retention periods, the rights in section 6, and
   anything about the video provider.
3. Check the video provider's actual contract against part three, and correct anything that does not
   match.
4. Print the four consents on one page each, so that declining one is easy.
5. Record the version of the notice against each consent decision — the software does this, and it
   is what proves which words the patient saw.
