"""Tests for the consent record.

The consent record is shaped by the Nigeria Data Protection Act 2023, and
these tests hold it to that shape:

* the clinical record does not rest on consent — it is made under
  S.30(1)(g), by a professional owing a duty of confidentiality;
* the optional uses each need a consent of their own, for the specific
  purpose (S.30(1)(a));
* each can be withdrawn on its own, and without withdrawing the others
  (S.35);
* the record of the consent is evidence: it is appended to, never edited.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
import uuid
from datetime import datetime, timezone

from telemedicine.audit import AuditLog
from telemedicine.consent import (
    ACKNOWLEDGED,
    GRANTED,
    OPTIONAL_PURPOSES,
    PURPOSE_MARKETING,
    PURPOSE_RESEARCH,
    PURPOSE_TEACHING,
    WITHDRAWN,
    ConsentService,
    InMemoryConsentStore,
    notice_digest,
)

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)


class Clock:
    """A clock that does not move unless it is told to."""

    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds=60):
        from datetime import timedelta
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


class ConsentServiceTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.audit = AuditLog(clock=self.clock)
        self.service = ConsentService(store=InMemoryConsentStore(),
                                      audit=self.audit, clock=self.clock)
        self.user = str(uuid.uuid4())

    # -- the clinical record is not a consent -----------------------------

    def test_the_clinical_record_cannot_be_consented_to(self):
        with self.assertRaises(ValueError) as caught:
            self.service.grant(self.user, "treatment", "2026-10-01")
        message = str(caught.exception)
        self.assertIn("S.30(1)(g)", message)
        self.assertIn("medical care", message)

    def test_an_unknown_purpose_is_refused(self):
        with self.assertRaises(ValueError):
            self.service.grant(self.user, "selling_the_data", "2026-10-01")

    # -- the optional uses -------------------------------------------------

    def test_granting_an_optional_purpose(self):
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.assertTrue(self.service.has_consent(self.user, PURPOSE_RESEARCH))
        self.assertEqual(self.service.granted_purposes(self.user), [PURPOSE_RESEARCH])

    def test_the_purposes_are_separate(self):
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.service.grant(self.user, PURPOSE_MARKETING, "2026-10-01")
        self.assertEqual(sorted(self.service.granted_purposes(self.user)),
                         sorted([PURPOSE_RESEARCH, PURPOSE_MARKETING]))

    def test_withdrawing_one_purpose_leaves_the_others(self):
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.service.grant(self.user, PURPOSE_TEACHING, "2026-10-01")
        self.service.withdraw(self.user, PURPOSE_RESEARCH)
        self.assertFalse(self.service.has_consent(self.user, PURPOSE_RESEARCH))
        self.assertTrue(self.service.has_consent(self.user, PURPOSE_TEACHING))

    def test_withdrawing_takes_effect_at_once(self):
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.service.withdraw(self.user, PURPOSE_RESEARCH)
        self.assertEqual(self.service.current_state(self.user, PURPOSE_RESEARCH),
                         WITHDRAWN)

    def test_withdrawing_something_never_granted(self):
        # A patient may withdraw a consent the practice thinks it holds.
        self.service.withdraw(self.user, PURPOSE_MARKETING)
        self.assertEqual(self.service.current_state(self.user, PURPOSE_MARKETING),
                         WITHDRAWN)
        self.assertFalse(self.service.has_consent(self.user, PURPOSE_MARKETING))

    def test_nothing_is_granted_at_the_start(self):
        self.assertEqual(self.service.granted_purposes(self.user), [])
        self.assertIsNone(self.service.current_state(self.user, PURPOSE_RESEARCH))

    # -- the notice is not a consent ---------------------------------------

    def test_the_notice_acknowledgement_is_not_a_consent(self):
        self.service.acknowledge_notice(self.user, "2026-10-01")
        self.assertTrue(self.service.notice_acknowledged(self.user))
        self.assertEqual(self.service.granted_purposes(self.user), [])
        self.assertEqual([event.kind for event in self.service.history(self.user)],
                         [ACKNOWLEDGED])

    def test_the_notice_acknowledgement_is_kept_apart_from_the_consents(self):
        self.service.acknowledge_notice(self.user, "2026-10-01")
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        kinds = [event.kind for event in self.service.history(self.user)]
        self.assertEqual(kinds, [ACKNOWLEDGED, GRANTED])
        # And the acknowledgement carries no purpose.
        self.assertIsNone(self.service.history(self.user)[0].purpose)

    # -- the record is evidence --------------------------------------------

    def test_the_record_is_appended_to_and_never_edited(self):
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.service.withdraw(self.user, PURPOSE_RESEARCH)
        history = self.service.history(self.user)
        self.assertEqual([event.kind for event in history], [GRANTED, WITHDRAWN])
        # The grant is still there, with the version it was given against.
        self.assertEqual(history[0].notice_version, "2026-10-01")

    def test_the_events_carry_the_time_and_the_method(self):
        event = self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01",
                                   method="in person", evidence="signed form")
        self.assertEqual(event.occurred_at, NOW)
        self.assertEqual(event.method, "in person")
        self.assertEqual(event.evidence, "signed form")
        self.assertTrue(event.event_id)

    def test_the_history_is_in_order(self):
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.clock.advance(60)
        self.service.withdraw(self.user, PURPOSE_RESEARCH)
        history = self.service.history(self.user)
        self.assertLess(history[0].occurred_at, history[1].occurred_at)

    # -- the audit trail ---------------------------------------------------

    def test_every_consent_event_is_audited(self):
        self.service.acknowledge_notice(self.user, "2026-10-01")
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.service.withdraw(self.user, PURPOSE_RESEARCH)
        actions = [entry.action for entry in self.audit.entries]
        self.assertEqual(actions, ["consent.notice_acknowledged",
                                   "consent.granted",
                                   "consent.withdrawn"])

    def test_the_audit_entry_names_the_purpose(self):
        self.service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        entry = self.audit.entries[0]
        self.assertEqual(entry.resource_type, "consent")
        self.assertIn(PURPOSE_RESEARCH, entry.detail)

    def test_the_service_works_without_an_audit_log(self):
        service = ConsentService(store=InMemoryConsentStore())
        service.grant(self.user, PURPOSE_RESEARCH, "2026-10-01")
        self.assertTrue(service.has_consent(self.user, PURPOSE_RESEARCH))

    # -- the notice --------------------------------------------------------

    def test_the_digest_of_a_notice_is_stable(self):
        first = notice_digest("The notice as it was read.")
        second = notice_digest("The notice as it was read.")
        self.assertEqual(first, second)
        self.assertNotEqual(first, notice_digest("A different notice."))


class ConsentStoreTest(unittest.TestCase):
    """The store keeps what it is given."""

    def test_the_store_holds_the_events(self):
        store = InMemoryConsentStore()
        service = ConsentService(store=store, clock=Clock())
        user = str(uuid.uuid4())
        service.grant(user, PURPOSE_RESEARCH, "2026-10-01")
        self.assertEqual(len(store.events_for(user)), 1)
        self.assertEqual(len(store.events_for_purpose(user, PURPOSE_RESEARCH)), 1)
        self.assertEqual(store.events_for_purpose(user, PURPOSE_MARKETING), [])


class OptionalPurposeTest(unittest.TestCase):
    def test_there_are_optional_purposes(self):
        self.assertIn(PURPOSE_RESEARCH, OPTIONAL_PURPOSES)
        self.assertIn(PURPOSE_TEACHING, OPTIONAL_PURPOSES)
        self.assertIn(PURPOSE_MARKETING, OPTIONAL_PURPOSES)

    def test_treatment_is_not_among_them(self):
        # The clinical record is made under S.30(1)(g), not by consent, so
        # "treatment" must never appear as something to consent to.
        self.assertNotIn("treatment", OPTIONAL_PURPOSES)
        self.assertNotIn("care", OPTIONAL_PURPOSES)


if __name__ == "__main__":
    unittest.main()
