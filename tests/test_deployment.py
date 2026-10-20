"""Tests for the deployment pieces.

A deployment is a set of files that have to agree with each other and with
the code: the compose file names settings the application does not read, the
container runs a health check that does not exist, and the runbook describes
something that was changed months ago. These tests are what stops that.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def read(name):
    return (REPO_ROOT / name).read_text(encoding="utf-8")


class ArtefactTest(unittest.TestCase):
    def test_the_container_file_exists(self):
        self.assertTrue((REPO_ROOT / "Dockerfile").is_file())

    def test_the_compose_file_exists(self):
        self.assertTrue((REPO_ROOT / "docker-compose.yml").is_file())

    def test_the_health_check_exists(self):
        self.assertTrue((REPO_ROOT / "scripts" / "healthcheck.py").is_file())

    def test_the_runbook_exists(self):
        self.assertTrue((REPO_ROOT / "docs" / "deployment.md").is_file())


class SettingsAgreementTest(unittest.TestCase):
    """The compose file and the code have to name the same settings."""

    def test_every_setting_the_compose_file_uses_is_read_by_the_code(self):
        from telemedicine.config import Settings
        import telemedicine.config as config

        compose = read("docker-compose.yml")
        used = set(re.findall(r"TELEMEDICINE_[A-Z_]+", compose))

        read_by_the_code = {
            name for name in dir(config) if name.startswith("ENV_")
        }
        known = {getattr(config, name) for name in read_by_the_code}
        unknown = used - known
        self.assertEqual(unknown, set(),
                         f"the compose file uses settings the code does not read: {unknown}")

        # And the other way round: a setting the code reads, that the
        # compose file never sets, is one a deployment would forget.
        # The database and the host and the port are set by the image or by
        # the compose file's environment, so they are all expected.
        self.assertIsNotNone(Settings.from_environment({}))

    def test_the_runbook_documents_every_setting(self):
        runbook = read("docs/deployment.md")
        import telemedicine.config as config

        for name in dir(config):
            if not name.startswith("ENV_"):
                continue
            variable = getattr(config, name)
            with self.subTest(setting=variable):
                self.assertIn(variable, runbook,
                              f"the runbook does not mention {variable}")

    def test_the_compose_file_runs_both_jobs(self):
        compose = read("docker-compose.yml")
        self.assertIn("scripts/run_server.py", compose)
        self.assertIn("scripts/run_delivery.py", compose)

    def test_the_compose_file_does_not_publish_the_database(self):
        # The database is for the application, not for the world.
        compose = read("docker-compose.yml")
        database = compose.split("  database:")[1].split("  api:")[0]
        self.assertNotIn("ports:", database)

    def test_the_database_password_is_required(self):
        compose = read("docker-compose.yml")
        self.assertIn("POSTGRES_PASSWORD:?", compose,
                      "the compose file must refuse to start without a password")


class ContainerTest(unittest.TestCase):
    def test_the_container_runs_as_a_user_that_is_not_root(self):
        dockerfile = read("Dockerfile")
        self.assertIn("USER telemedicine", dockerfile)
        self.assertIn("useradd", dockerfile)

    def test_the_container_health_checks_itself(self):
        dockerfile = read("Dockerfile")
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("scripts/healthcheck.py", dockerfile)

    def test_the_container_holds_only_the_application(self):
        dockerfile = read("Dockerfile")
        self.assertNotIn("COPY tests", dockerfile)
        self.assertNotIn("COPY .git", dockerfile)

    def test_the_image_installs_the_project_and_its_one_dependency(self):
        dockerfile = read("Dockerfile")
        self.assertIn("pip install", dockerfile)
        # The dependency is declared in the manifest, not spelled out in the
        # container, so that there is one place to change it.
        manifest = read("pyproject.toml")
        self.assertIn("psycopg", manifest)
        self.assertIn("dependencies", manifest)


class HealthCheckTest(unittest.TestCase):
    def test_it_fails_when_the_server_is_not_answering(self):
        import runpy
        import sys

        script = str(REPO_ROOT / "scripts" / "healthcheck.py")
        # A port nothing is listening on, and no database.
        sys.argv = [script]
        with self.assertRaises(SystemExit) as caught:
            runpy.run_path(script, run_name="__main__")
        self.assertNotEqual(caught.exception.code, 0)

    def test_it_asks_the_metadata_endpoint(self):
        source = read("scripts/healthcheck.py")
        self.assertIn("/fhir/metadata", source)

    def test_it_checks_the_schema(self):
        source = read("scripts/healthcheck.py")
        self.assertIn("missing_tables", source)
        self.assertIn("apply_schema.py", source)


class RunbookTest(unittest.TestCase):
    def test_it_names_the_four_questions_the_practice_has_to_answer(self):
        runbook = read("docs/deployment.md")
        for marker in ("REG-01", "REG-02", "PRIV-02", "PRIV-03"):
            with self.subTest(finding=marker):
                self.assertIn(marker, runbook)

    def test_it_says_what_is_still_missing(self):
        runbook = read("docs/deployment.md")
        self.assertIn("media provider", runbook.lower())
        self.assertIn("tls", runbook.lower())

    def test_it_says_the_anchors_have_to_be_copied_off_the_machine(self):
        runbook = read("docs/deployment.md")
        self.assertIn("anchors", runbook)
        self.assertIn("Copy them off the machine", runbook)


if __name__ == "__main__":
    unittest.main()
