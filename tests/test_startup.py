"""What the application says when it cannot start.

A deployment that fails with a raw ``ImportError`` three frames deep is
worse than one that fails with a sentence. These tests are about the
messages.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock


class MissingDriverTest(unittest.TestCase):
    def test_the_message_says_how_to_install_the_driver(self):
        from telemedicine.persistence import database

        with mock.patch.dict("sys.modules", {"psycopg": None}):
            with self.assertRaises(database.DriverMissing) as caught:
                database.import_driver()
        message = str(caught.exception)
        self.assertIn("psycopg", message)
        self.assertIn("pip install", message)

    def test_the_apply_script_reports_it_and_fails(self):
        import runpy
        import sys

        from telemedicine.persistence import database

        script = str(_repo_path("scripts/apply_schema.py"))
        argv = [script, "postgresql://user@host/telemedicine"]
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            with mock.patch.object(sys, "argv", argv):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as caught:
                        runpy.run_path(script, run_name="__main__")
        self.assertNotEqual(caught.exception.code, 0)
        self.assertIn("psycopg", stderr.getvalue())

    def test_the_server_reports_it_and_does_not_start(self):
        import runpy
        import sys

        script = str(_repo_path("scripts/run_server.py"))
        argv = [script]
        environment = {"TELEMEDICINE_DATABASE_URL": "postgresql://user@host/telemedicine"}
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            with mock.patch.dict("os.environ", environment, clear=True):
                with mock.patch.object(sys, "argv", argv):
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as caught:
                            runpy.run_path(script, run_name="__main__")
        self.assertNotEqual(caught.exception.code, 0)
        self.assertIn("psycopg", stderr.getvalue())


class UnreachableDatabaseTest(unittest.TestCase):
    def test_an_unreachable_database_is_reported_plainly(self):
        from telemedicine.persistence.database import (
            Database,
            DriverMissing,
            SchemaError,
        )

        database = Database("postgresql://nobody@127.0.0.1:1/nothing")
        try:
            database.check_connection()
        except DriverMissing:
            # No driver on this machine: the message about that is checked
            # above, and the one about an unreachable database cannot be.
            self.skipTest("the PostgreSQL driver is not installed here")
        except SchemaError as error:
            self.assertIn("could not be reached", str(error))
        else:
            self.fail("the connection to a port with nothing on it should fail")

    def test_the_application_does_not_start_without_its_schema(self):
        from telemedicine.persistence.database import Database, SchemaError

        database = Database("postgresql://nobody@127.0.0.1:1/nothing")
        with mock.patch.object(Database, "check_connection"):
            with mock.patch.object(Database, "missing_tables", return_value=["patient"]):
                from telemedicine.application import build_application
                from telemedicine.config import Settings

                with self.assertRaises(RuntimeError) as caught:
                    build_application(Settings(database_url="postgresql://x@127.0.0.1:1/y"))
                self.assertIn("scripts/apply_schema.py", str(caught.exception))


def _repo_path(*parts):
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.joinpath(*parts)


if __name__ == "__main__":
    unittest.main()
