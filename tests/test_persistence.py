"""Tests for the persistence layer.

These need a PostgreSQL server. They are skipped when there is none, so
that the suite still runs on a machine without a database — and they are
run in the continuous integration, which has one.

The connection string comes from ``TELEMEDICINE_TEST_DSN``:

    TELEMEDICINE_TEST_DSN="postgresql://postgres@localhost/postgres" \\
        python3 -m unittest tests.test_persistence -v

Each test class works in a database of its own, created fresh and dropped
afterwards. That is not tidiness: the audit log is append-only, and its
trigger refuses a ``TRUNCATE`` exactly as it should, so a test cannot clear
it.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone

DSN = os.environ.get("TELEMEDICINE_TEST_DSN")

try:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    HAVE_DRIVER = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_DRIVER = False

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _user_id():
    """A user id in the shape the audit log's uuid column expects."""
    return str(uuid.uuid4())


def _fresh_database(name):
    """Create a database of its own and return a Database for it.

    Returns None when there is no server, which skips the test.
    """
    if not DSN or not HAVE_DRIVER:
        return None
    from telemedicine.persistence.database import Database
    info = conninfo_to_dict(DSN)
    admin = make_conninfo(**{**info, "dbname": "postgres"})
    try:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            connection.execute(f'CREATE DATABASE "{name}"')
    except Exception as error:  # pragma: no cover - depends on the environment
        raise unittest.SkipTest(f"the database is not reachable: {error}") from error
    return Database(make_conninfo(**{**info, "dbname": name}))


class DatabaseTestCase(unittest.TestCase):
    """A database of its own for every test.

    Not tidiness: the audit log is append-only and its trigger refuses a
    TRUNCATE, so a test cannot share a log with another one and start from
    an empty state.
    """

    database_name = "telemedicine_test"

    def setUp(self):
        self.database = _fresh_database(self.database_name)
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")
        self.apply_schema()

    def apply_schema(self):
        self.report = self.database.apply_schema()


class SchemaTest(DatabaseTestCase):
    """The schema files, applied to a real server for the first time."""

    database_name = "telemedicine_schema_test"

    def test_the_schema_applies(self):
        tables = self.database.tables()
        for name in ("appointment", "audit_log", "auth_lockout", "encounter",
                     "medication_request", "patient", "prescription_document", "practitioner",
                     "schedule_slot", "user_account"):
            with self.subTest(table=name):
                self.assertIn(name, tables)

    def test_the_report_says_exactly_what_was_skipped(self):
        # The exclusion constraint on the slots needs the btree_gist extension.
        # Where the server has it, nothing is skipped; where it does not, the
        # report says so, and says which statement was left out.
        skipped = " ".join(self.report.skipped)
        if self.report.missing_extensions:
            self.assertIn("btree_gist", self.report.missing_extensions)
            self.assertIn("btree_gist", skipped)
            self.assertIn("schedule_slot_no_overlap", skipped)
        else:
            self.assertEqual(self.report.skipped, [])

    def test_the_schema_is_re_runnable(self):
        # A deployment that applies the schema on every start must not break.
        report = self.database.apply_schema()
        self.assertIn("schema.sql", report.applied)

    def test_the_audit_log_refuses_to_be_emptied(self):
        # The append-only trigger is not decoration.
        from telemedicine.persistence.database import Database
        with self.assertRaises(Exception):
            with self.database.transaction() as cursor:
                cursor.execute("TRUNCATE audit_log")


class DurableAuditLogTest(DatabaseTestCase):
    """The audit log that survives a restart."""

    database_name = "telemedicine_audit_test"

    def setUp(self):
        super().setUp()
        from telemedicine.persistence.audit_store import PostgresAuditLog
        self.log = PostgresAuditLog(self.database)

    def test_an_entry_is_written_and_verifies(self):
        entry = self.log.append(
            actor_user_id=_user_id(), actor_role="patient", action="record.read",
            resource_type="patient", resource_id="patient-1", outcome="success",
            detail="read patient record patient-1")
        self.assertEqual(entry.sequence, 1)
        self.assertTrue(self.log.verify_chain())
        self.assertIsNone(self.log.find_chain_break())

    def test_the_log_survives_a_restart(self):
        self.log.append(
            actor_user_id=_user_id(), actor_role="patient", action="record.read",
            resource_type="patient", resource_id="patient-1", outcome="success")
        # A new object is a new process as far as the log is concerned: the
        # entries are in the database, not in the object.
        from telemedicine.persistence.audit_store import PostgresAuditLog
        reopened = PostgresAuditLog(self.database)
        self.assertEqual(len(reopened), 1)
        self.assertTrue(reopened.verify_chain())
        self.assertEqual(reopened.head_hash(), self.log.head_hash())

    def test_the_chain_links_the_entries(self):
        first = self.log.append(
            actor_user_id=_user_id(), actor_role="patient", action="record.read",
            resource_type="patient", resource_id="patient-1", outcome="success")
        second = self.log.append(
            actor_user_id=_user_id(), actor_role="patient", action="record.read",
            resource_type="patient", resource_id="patient-2", outcome="success")
        self.assertEqual(second.previous_hash, first.entry_hash)
        self.assertTrue(self.log.verify_chain())

    def test_two_writers_do_not_fork_the_chain(self):
        # The advisory lock in the transaction is what stops two writers
        # reading the same chain head.
        errors = []

        def writer(index):
            try:
                for _ in range(5):
                    self.log.append(
                        actor_user_id=str(uuid.uuid4()), actor_role="patient",
                        action="record.read", resource_type="patient",
                        resource_id=str(uuid.uuid4()), outcome="success")
            except Exception as error:  # pragma: no cover - a failure is the point
                errors.append(error)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.log), 20)
        self.assertTrue(self.log.verify_chain())
        self.assertIsNone(self.log.find_chain_break())

    def test_a_tampered_entry_is_detected(self):
        self.log.append(
            actor_user_id=_user_id(), actor_role="patient", action="record.read",
            resource_type="patient", resource_id="patient-1", outcome="success")
        # The trigger refuses the update, so the tampering is done with the
        # trigger out of the way — which is exactly what an attacker with
        # write access would have to do.
        with self.database.transaction() as cursor:
            cursor.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_or_delete")
            cursor.execute("UPDATE audit_log SET detail = 'changed' WHERE sequence = 1")
            cursor.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_or_delete")
        self.assertFalse(self.log.verify_chain())
        self.assertEqual(self.log.find_chain_break(), 1)

    def test_the_filters_work(self):
        first_actor = _user_id()
        second_actor = _user_id()
        self.log.append(
            actor_user_id=first_actor, actor_role="patient", action="record.read",
            resource_type="patient", resource_id="patient-1", outcome="success")
        self.log.append(
            actor_user_id=second_actor, actor_role="practitioner", action="record.read",
            resource_type="patient", resource_id="patient-2", outcome="denied")
        self.assertEqual(len(self.log.entries_for_resource("patient", "patient-1")), 1)
        self.assertEqual(len(self.log.entries_for_actor(second_actor)), 1)
        self.assertEqual(len(self.log.entries_for_outcome("denied")), 1)

    def test_an_unknown_actor_is_stored_as_null(self):
        # The actor id column is a uuid, so a login for an account that does
        # not exist has no actor at all rather than a placeholder.
        entry = self.log.append(
            actor_user_id=None, actor_role="unknown", action="auth.login",
            resource_type="user_account", resource_id="anonymous", outcome="denied")
        self.assertIsNone(entry.actor_user_id)
        self.assertTrue(self.log.verify_chain())


class LockoutStoreContractTest(DatabaseTestCase):
    """The in-memory store and the database store have to behave the same."""

    database_name = "telemedicine_lockout_test"

    def stores(self):
        from telemedicine.persistence.lockout import (
            InMemoryLockoutStore,
            PostgresLockoutStore,
        )
        with self.database.transaction() as cursor:
            cursor.execute("TRUNCATE auth_lockout")
        return [InMemoryLockoutStore(), PostgresLockoutStore(self.database)]

    def test_both_stores_count_lock_and_clear(self):
        for store in self.stores():
            with self.subTest(store=type(store).__name__):
                key = "ada@example.org"
                self.assertEqual(store.attempts(key), 0)
                self.assertIsNone(store.locked_until(key))
                self.assertFalse(store.is_locked(key, NOW))

                self.assertEqual(store.record_failure(key, NOW), 1)
                self.assertEqual(store.record_failure(key, NOW), 2)
                self.assertEqual(store.attempts(key), 2)

                store.set_locked_until(key, NOW + timedelta(minutes=5))
                self.assertTrue(store.is_locked(key, NOW))
                self.assertFalse(store.is_locked(key, NOW + timedelta(minutes=6)))

                store.record_success(key)
                self.assertEqual(store.attempts(key), 0)
                self.assertIsNone(store.locked_until(key))


class SharedLockoutTest(DatabaseTestCase):
    """The property that matters: two instances share the counter."""

    database_name = "telemedicine_shared_test"

    def setUp(self):
        super().setUp()
        from telemedicine.persistence.lockout import PostgresLockoutStore
        self.store = PostgresLockoutStore(self.database)

    def test_two_stores_share_the_counter(self):
        from telemedicine.persistence.lockout import PostgresLockoutStore
        other = PostgresLockoutStore(self.database)
        self.assertEqual(self.store.record_failure("ada@example.org", NOW), 1)
        self.assertEqual(other.record_failure("ada@example.org", NOW), 2)
        self.assertEqual(other.attempts("ada@example.org"), 2)
        other.set_locked_until("ada@example.org", NOW + timedelta(minutes=5))
        self.assertTrue(self.store.is_locked("ada@example.org", NOW))

    def test_a_service_locks_an_account_out_after_the_threshold(self):
        from telemedicine.auth import AuthService
        from telemedicine.errors import AuthenticationError
        from telemedicine.models import Role
        from telemedicine.persistence.audit_store import PostgresAuditLog
        service = AuthService(audit=PostgresAuditLog(self.database), lockout=self.store,
                              password_iterations=1000)
        service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                         record_id="patient-1")

        for _ in range(5):
            with self.assertRaises(AuthenticationError):
                service.authenticate("ada@example.org", "not-the-passphrase")

        # The account is locked now, and the right password does not get in.
        with self.assertRaises(AuthenticationError):
            service.authenticate("ada@example.org", "a-long-passphrase")

    def test_a_successful_login_clears_the_counter(self):
        from telemedicine.auth import AuthService
        from telemedicine.errors import AuthenticationError
        from telemedicine.models import Role
        from telemedicine.persistence.audit_store import PostgresAuditLog
        service = AuthService(audit=PostgresAuditLog(self.database), lockout=self.store,
                              password_iterations=1000)
        service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                         record_id="patient-1")
        for _ in range(3):
            with self.assertRaises(AuthenticationError):
                service.authenticate("ada@example.org", "not-the-passphrase")
        self.assertEqual(self.store.attempts("ada@example.org"), 3)
        service.authenticate("ada@example.org", "a-long-passphrase")
        self.assertEqual(self.store.attempts("ada@example.org"), 0)

    def test_the_lock_is_audited(self):
        from telemedicine.auth import AuthService
        from telemedicine.errors import AuthenticationError
        from telemedicine.models import Role
        from telemedicine.persistence.audit_store import PostgresAuditLog
        audit = PostgresAuditLog(self.database)
        service = AuthService(audit=audit, lockout=self.store, password_iterations=1000)
        service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                         record_id="patient-1")
        for _ in range(5):
            with self.assertRaises(AuthenticationError):
                service.authenticate("ada@example.org", "not-the-passphrase")
        with self.assertRaises(AuthenticationError):
            service.authenticate("ada@example.org", "a-long-passphrase")
        locked = [entry for entry in audit.entries_for_outcome("denied")
                  if entry.action == "auth.locked"]
        self.assertTrue(locked)


if __name__ == "__main__":
    unittest.main()
