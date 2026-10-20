# Persistence — design

- **Feature:** `ENG-007` — the schema applied for the first time, a durable audit log, and a lockout
  that several instances share
- **Status:** Implemented and tested against a real PostgreSQL 16.2. The clinical repositories are
  still in memory; what this feature adds is the database itself, the schema that runs against it,
  and the two pieces of the compliance review that need one.
- **Owner:** `OpenCode-20261020-3dafd2c8`

## 1. Why this feature exists

Every pull request in this project so far carried the same caveat: *the DDL has not been executed*.
The schema had never been run against a PostgreSQL server, because there was none. That is not a
small caveat — a schema that has never run is a schema that does not work.

It turned out to be worse than that. **Applying the schema to a real server for the first time found
three defects that no amount of reading would have found**, and they are in the files that every
other feature depends on:

| Defect | What was wrong | What happens now |
| --- | --- | --- |
| A missing unique constraint | `medication_request` has a composite foreign key to `encounter (id, patient_id, practitioner_id)`, and that key was **never declared unique**. PostgreSQL refuses the whole file | `encounter_identity` is declared, and the schema applies |
| An unmarked extension dependency | `schedule_slot_practitioner_range` is a GiST index over a `uuid`, which needs the `btree_gist` extension. Only the exclusion constraint was marked as needing it | Both statements are marked with `-- @requires-extension btree_gist` |
| A type mismatch between the code and the schema | The `audit_log.actor_user_id` column is a `uuid`, but the application writes the string `"anonymous"` for a login against an account that does not exist | The actor of an unknown account is `None`, and the schema says so |

The third one was found by the database refusing the value. The first was found by the database
refusing the table.

## 2. What this feature adds

- **`telemedicine/persistence/database.py`** — the connection, the transactions, and the schema
  application. The schema files are the source of truth; this module reads them.
- **`telemedicine/persistence/audit_store.py`** — the audit log in the `audit_log` table. The same
  `append` interface as the in-memory log of ENG-002, so a service can be given either.
- **`telemedicine/persistence/lockout.py`** — the failed-attempt counter, in the `auth_lockout` table
  and in memory, behind one interface.
- **`db/security_schema.sql`** — the `auth_lockout` table.
- **`pyproject.toml`** — the dependency manifest. The project now has **one** third-party
  dependency, the PostgreSQL driver.
- **`scripts/apply_schema.py`** — the command that applies the schema.
- **`tests/test_persistence.py`** — 16 tests that need a server and are skipped without one.

## 3. The dependency

**The project gains a dependency: `psycopg[binary]`.** There is no PostgreSQL driver in the
standard library, and there is no honest way to persist a clinical record without one. Everything
else stays standard library only.

That is a real change to the project's character, and it is recorded here rather than buried:

- the *application* code — the services, the FHIR layer, the video rooms — is still standard
  library only, and the tests for it still need nothing installed;
- the *persistence* layer is the only part that needs the driver, and it is imported lazily, so the
  package still imports on a machine without it;
- the test suite runs without the driver: the 16 persistence tests skip, and the other 294 run.

The alternative — staying standard library only — means the project never keeps a record of
anything, and OPS-002 can never happen.

## 4. The schema application

```bash
python3 scripts/apply_schema.py "postgresql://user@host/database"
```

The files are applied in order: the clinical tables, the accounts and the audit log, the prescription
document, and the lockout. Each statement runs in its own transaction, so a failure leaves the
earlier statements in place and the report says how far it got.

**The files are re-runnable.** Tables and indexes are created if they are not there, functions are
replaced, and triggers are dropped and created again. A deployment that applies the schema on every
start does not break, and the schema is not a one-time event that has to be scheduled.

**Statements that need an extension the server does not have are skipped, and the report says so.**
`db/schema.sql` asks for `btree_gist`, which is part of PostgreSQL's contrib. A server without contrib
— some minimal distributions, and the bundled one used in development — cannot create the GiST
exclusion constraint that stops a practitioner holding two overlapping slots. The statements that
need it are marked in the file with a comment, and the applier skips exactly those:

```
applied: schema.sql, auth_schema.sql, prescription_schema.sql, security_schema.sql
skipped: schema.sql: CREATE EXTENSION IF NOT EXISTS btree_gist; (needs btree_gist); ...
missing extensions: btree_gist
```

The rule the constraint enforces is also enforced in the application — `SlotService.create_slot`
refuses a slot that overlaps another of the same practitioner — so the guarantee does not depend on
the extension. What the extension adds is the guarantee against two instances racing to create
overlapping slots at the same moment.

**The splitter understands the schema.** Applying a file means splitting it into statements, and the
two things a naive splitter gets wrong are a semicolon inside a string and a semicolon inside the
dollar-quoted body of a function. ENG-002's audit log defines a trigger function that way, and
splitting it on the first semicolon produced a syntax error rather than a function.

## 5. The durable audit log

SEC-06 of the compliance review said the audit log was "not durable, and a restart loses it". It is
now durable: the entries are rows, and the chain is verified from the rows.

The one hard part is the chain itself. Every entry hashes the entry before it, so two writers that
read the same chain head would fork it. The append therefore happens inside a transaction that
holds a PostgreSQL advisory lock, and the chain head is read in that same transaction:

```sql
SELECT pg_advisory_xact_lock(...);
SELECT entry_hash FROM audit_log ORDER BY sequence DESC LIMIT 1;
INSERT INTO audit_log ...;
```

The lock is released when the transaction ends, whether it committed or not. The test that matters
is the one that starts four threads writing at once and then checks that the chain still verifies —
it does, and all twenty entries are there.

Reading an entry back needed care: the driver hands back a `uuid` and a `datetime`, and the hash was
computed over the strings. Without normalising them, every entry read from the database would look
like a broken link.

**What is still open:** the chain is only as good as the database it is in. SEC-07 — anchoring the
chain head somewhere an attacker cannot rewrite — needs a system outside the database, and there is
none. A digest published periodically to a separate store, or a write-once store for the log, is
still to do.

## 6. The shared lockout

SEC-04 said the login had no lockout, and that the columns in the schema were "not the fix: a
counter that lives in one process is wrong the moment there are two".

The counter is now a store, with two implementations, and the service does not know which it has:

| | |
| --- | --- |
| `InMemoryLockoutStore` | one process, and the tests |
| `PostgresLockoutStore` | the `auth_lockout` table, shared by every instance |

The policy:

- five consecutive failures lock the key for a minute;
- every further failure doubles the lock, up to fifteen minutes;
- a successful login clears the counter;
- the key is the **normalised email address**, whether or not the account exists — a counter that
  only existed for known accounts would tell an attacker which addresses are registered.

The test that matters is the one that gives two stores the same database and checks that they see
each other's counts, and the one that locks an account out and then tries the *right* password.

**What is still open:** the lockout is per account, not per source address. An attacker who knows a
victim's address can lock that account out by failing five times. That is a denial of service, not a
breach, and the fix is to count per address as well as per account, which needs the source address
of the request — which the HTTP layer does not currently pass to the service.

## 7. Amendments to earlier features

| File | Amendment | Why |
| --- | --- | --- |
| `db/schema.sql` | `encounter_identity` added; the two extension-dependent statements marked; the tables, indexes and triggers made re-runnable | The first is a defect the database found; the second is a marker so that the applier can skip them; the third is what makes the apply safe to repeat |
| `db/auth_schema.sql` | The tables, indexes and triggers made re-runnable; the comment on `actor_user_id` corrected | The comment said the application writes `'anonymous'` into a `uuid` column, which it cannot |
| `db/prescription_schema.sql` | The tables, indexes and triggers made re-runnable | The same |
| `telemedicine/audit.py` | The actor of an entry may be `None` | A login for an account that does not exist has no actor, and the column is a `uuid` |
| `telemedicine/auth.py` | The lockout; the unknown actor has no id | SEC-04; and the type mismatch above |
| `tests/test_schema.py`, `tests/test_auth_schema.py`, `tests/test_prescription_schema.py` | The schema parser knows about `IF NOT EXISTS` | The files changed shape |

## 8. Known gaps

1. **The clinical data is still in memory.** The repositories of the application hold patients,
   appointments, encounters and prescriptions in dictionaries. The tables they belong to exist, and
   the schema runs, but nothing writes to them yet. That is the next piece of work, and it is the
   last thing between this project and a deployment.
2. **The account and session tables are also unused.** `user_account` and `auth_session` are
   created, and the audit log and the lockout use them, but the accounts themselves are still held
   in memory.
3. **No migration history.** The schema is applied by re-running the files, which works because
   they are re-runnable — but there is no record of which version a database was built from, and no
   way to step a database forward one version at a time. A deployment that changes a table needs a
   migration, and the tooling for that is not here.
4. **The driver is a dependency.** The application is still standard library only, but the project
   is not, and the continuous integration has to install the driver.
5. **The database tests are skipped without a server.** The suite runs anywhere; the persistence
   tests only where there is a PostgreSQL. The continuous integration has one, and the developer
   extra installs a server that runs itself.
6. **`btree_gist` is not everywhere.** Without it, the exclusion constraint is skipped and the
   guarantee against racing writers falls back to the application check.
7. **The lockout is per account, not per address** (§6).
8. **The audit chain is not anchored outside the database** (§5).
9. **There is no connection pooling.** Every operation opens a connection. That is fine for a
   development server and wrong for a deployment under load.
10. **The audit log and the lockout are in the same database as the clinical data.** A compromise
    between keeping them apart and keeping the transaction simple, and one that has to be reviewed
    before a deployment: an attacker who can write to the audit log may be able to write to the
    clinical tables.

## 9. What the successor needs

- **The clinical repositories**, which is the last big piece of engineering.
- **A migration history**, with the tooling to apply it and to record what a database was built
  from.
- **Connection pooling** and a deployment behind a real server.
- **The media transport** of ENG-004, which needs a provider.
- **The remaining Group 1 items** of the compliance review: the chain anchor, the encryption at
  rest, the retention policy, TLS, and the consent capture — of which the last is the practice's
  answer rather than engineering's.
