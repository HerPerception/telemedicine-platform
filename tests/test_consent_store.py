"""Tests for the consent record in the database.

These need a PostgreSQL server. They are skipped when there is none, so
that the suite still runs on a machine without a database — and they are
run in the continuous integration, which has one.

The connection string comes from ``TELEMEDICINE_TEST_DSN``:

    TELEMEDICINE_TEST_DSN="postgresql://postgres@localhost/postgres" \\
        python3 -m unittest tests.test_consent_store -v

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
import uuid
from datetime import datetime, timezone

from tests.test_persistence import _fresh_database

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)


class ConsentStoreTestCase(unittest.TestCase):
    """A database of its own for every test."""

    database_name = "telemedicine_consent_test"

    def setUp(self):
        self.database = _fresh_database(self.database_name)
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        from telemedicine.consent import ConsentService
        from telemedicine.persistence.consent_store import PostgresConsentStore
        self.store = PostgresConsentStore(self.database)
        self.service = ConsentService(store=self.store)
        self.user = str(uuid.uuid4())


class ConsentStoreTest(ConsentStoreTestCase):
    def test_a_consent_round_trips(self):
        self.service.grant(self.user, "research", "2026-10-01", evidence="form 4")
        events = self.store.events_for(self.user)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "granted")
        self.assertEqual(events[0].purpose, "research")
        self.assertEqual(events[0].notice_version, "2026-10-01")
        self.assertEqual(events[0].evidence, "form 4")

    def test_the_events_survive_a_restart(self):
        self.service.grant(self.user, "research", "2026-10-01")
        from telemedicine.persistence.consent_store import PostgresConsentStore
        reopened = PostgresConsentStore(self.database)
        self.assertEqual(len(reopened.events_for(self.user)), 1)
        self.assertTrue(self.service.has_consent(self.user, "research"))

    def test_a_withdrawal_is_a_second_row_and_not_a_change(self):
        self.service.grant(self.user, "research", "2026-10-01")
        self.service.withdraw(self.user, "research")
        events = self.store.events_for(self.user)
        self.assertEqual([event.kind for event in events], ["granted", "withdrawn"])
        self.assertFalse(self.service.has_consent(self.user, "research"))

    def test_one_purpose_is_not_another(self):
        self.service.grant(self.user, "research", "2026-10-01")
        self.assertEqual(self.store.events_for_purpose(self.user, "marketing"), [])

    def test_the_acknowledgement_of_the_notice_is_stored_too(self):
        self.service.acknowledge_notice(self.user, "2026-10-01")
        events = self.store.events_for(self.user)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "acknowledged")
        self.assertIsNone(events[0].purpose)

    def test_the_table_refuses_an_update(self):
        self.service.grant(self.user, "research", "2026-10-01")
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE consent_event SET notice_version = 'changed'")
        self.assertIn("append-only", str(caught.exception))

    def test_the_table_refuses_a_delete(self):
        self.service.grant(self.user, "research", "2026-10-01")
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM consent_event")
        self.assertIn("append-only", str(caught.exception))

    def test_the_table_refuses_to_be_truncated(self):
        self.service.grant(self.user, "research", "2026-10-01")
        with self.assertRaises(Exception) as caught:
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("TRUNCATE consent_event")
        self.assertIn("append-only", str(caught.exception))

    def test_an_unknown_purpose_is_refused_by_the_table_too(self):
        with self.assertRaises(Exception):
            with self.database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO consent_event (user_id, kind, purpose)"
                        " VALUES (%s, 'granted', 'selling_the_data')",
                        (self.user,))


if __name__ == "__main__":
    unittest.main()
