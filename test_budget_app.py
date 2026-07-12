"""Unit tests for the parts of budget_app that have logic worth pinning down:
the optional Windows AD / Entra access control, and the MariaDB
create-database-if-missing flow. No database server or Windows host is needed --
the OS calls (``subprocess``) and the ``pymysql`` driver are stubbed.

Run with:  python3 -m unittest -v test_budget_app
"""
import io
import os
import tempfile
import types
import unittest
from unittest import mock

import budget_app as ba


def fake_run(mapping):
    """Build a subprocess.run stub. mapping: argv[0] -> (returncode, stdout)."""
    def _run(args, **kwargs):
        rc, out = mapping.get(args[0], (1, ""))
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")
    return _run


WHOAMI = (
    '"Everyone","Well-known group","S-1-1-0","Mandatory group"\n'
    '"CONTOSO\\Budget-Users","Group","S-1-5-21-1-2-3-1104","Mandatory group"\n'
    '"BUILTIN\\Users","Alias","S-1-5-32-545","Mandatory group"\n'
)
DSREG_DOMAIN = " DomainJoined : YES\n AzureAdJoined : NO\n"
DSREG_ENTRA = " DomainJoined : NO\n AzureAdJoined : YES\n"
DSREG_NONE = " DomainJoined : NO\n AzureAdJoined : NO\n"


class AccessControlTests(unittest.TestCase):
    def _reason(self, *, platform="win32", dsreg=DSREG_DOMAIN, whoami=WHOAMI,
                group="Budget-Users", deny_on_error=True, userdns=None):
        mapping = {}
        if dsreg is not None:
            mapping["dsregcmd"] = (0, dsreg)
        if whoami is not None:
            mapping["whoami"] = (0, whoami)
        env = {} if userdns is None else {"USERDNSDOMAIN": userdns}
        policy = ba.AccessPolicy(group, deny_on_error) if group else None
        with mock.patch.object(ba.sys, "platform", platform), \
                mock.patch.object(ba.subprocess, "run", fake_run(mapping)), \
                mock.patch.dict(ba.os.environ, env, clear=False):
            ba.os.environ.pop("USERDNSDOMAIN", None)
            if userdns:
                ba.os.environ["USERDNSDOMAIN"] = userdns
            return ba.access_denied_reason(policy)

    def test_no_policy_allows(self):
        self.assertIsNone(self._reason(group=None))

    def test_non_windows_allows(self):
        self.assertIsNone(self._reason(platform="darwin", dsreg=None, whoami=None))

    def test_standalone_windows_allows(self):
        self.assertIsNone(self._reason(dsreg=DSREG_NONE, userdns=None))

    def test_domain_member_by_bare_name_allows(self):
        self.assertIsNone(self._reason(group="Budget-Users"))

    def test_domain_member_by_qualified_name_allows(self):
        self.assertIsNone(self._reason(group="CONTOSO\\Budget-Users"))

    def test_domain_non_member_denies(self):
        self.assertIsNotNone(self._reason(group="Finance-Admins"))

    def test_entra_member_by_sid_allows(self):
        self.assertIsNone(
            self._reason(dsreg=DSREG_ENTRA, group="S-1-5-21-1-2-3-1104"))

    def test_unverifiable_fails_closed_by_default(self):
        # whoami unavailable on a joined PC -> deny when deny_on_error=True.
        self.assertIsNotNone(self._reason(whoami=None, deny_on_error=True))

    def test_unverifiable_can_fail_open(self):
        self.assertIsNone(self._reason(whoami=None, deny_on_error=False))

    def test_env_fallback_treats_as_domain_joined(self):
        # No dsregcmd, but a domain logon exposes USERDNSDOMAIN.
        self.assertIsNotNone(
            self._reason(dsreg=None, group="Finance-Admins", userdns="contoso.com"))

    def test_undeterminable_join_fails_closed_by_default(self):
        # dsregcmd fails and no USERDNSDOMAIN (e.g. Entra PC where the check
        # was blocked): join state is unknown -> deny when deny_on_error=True.
        self.assertIsNotNone(
            self._reason(dsreg=None, userdns=None, deny_on_error=True))

    def test_undeterminable_join_can_fail_open(self):
        self.assertIsNone(
            self._reason(dsreg=None, userdns=None, deny_on_error=False))

    def test_load_access_config_absent_section(self):
        parser_read = mock.Mock(return_value=[])
        with mock.patch("configparser.ConfigParser.read", parser_read):
            self.assertIsNone(ba.load_access_config("nonexistent.ini"))


class CreateDatabaseTests(unittest.TestCase):
    """The MariaDB 'unknown database' -> CREATE DATABASE -> retry flow."""

    def _make_db_stub(self):
        """A BudgetDB whose __init__ is bypassed, with a mariadb config."""
        db = ba.BudgetDB.__new__(ba.BudgetDB)
        db.config = ba.DBConfig(
            "mariadb",
            dict(host="h", port=3306, user="u", password="p", database="bud`get"),
            "MariaDB test")
        db.backend = "mariadb"
        return db

    def test_create_database_escapes_backticks(self):
        captured = {}

        class Cur:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, params=None): captured["sql"] = sql

        class Conn:
            def cursor(self): return Cur()
            def close(self): pass

        def connect(**kwargs):
            captured["had_database"] = "database" in kwargs
            return Conn()

        db = self._make_db_stub()
        with mock.patch.object(ba.pymysql, "connect", connect):
            db._create_database()

        # Connected to the server without selecting a database...
        self.assertFalse(captured["had_database"])
        # ...and doubled the embedded backtick in the identifier.
        self.assertEqual(
            captured["sql"],
            "CREATE DATABASE IF NOT EXISTS `bud``get` CHARACTER SET utf8mb4")

    def test_connect_creates_db_then_retries_on_1049(self):
        attempts = []

        class Conn:
            def cursor(self):
                class C:
                    def __enter__(s): return s
                    def __exit__(s, *a): return False
                    def execute(s, *a, **k): pass
                return C()
            def close(self): pass

        def connect(**kwargs):
            attempts.append("database" in kwargs)
            # First attempt (with database) fails: unknown database.
            if kwargs.get("database") and attempts.count(True) == 1:
                raise ba.pymysql.err.OperationalError(1049, "Unknown database")
            return Conn()

        db = self._make_db_stub()
        with mock.patch.object(ba.pymysql, "connect", connect):
            conn = db._connect_mariadb()

        self.assertIsInstance(conn, Conn)
        # with-db (fail), no-db (create), with-db (retry succeeds)
        self.assertEqual(attempts, [True, False, True])

    def test_other_operational_error_propagates(self):
        def connect(**kwargs):
            raise ba.pymysql.err.OperationalError(1045, "Access denied")

        db = self._make_db_stub()
        with mock.patch.object(ba.pymysql, "connect", connect):
            with self.assertRaises(ba.pymysql.err.OperationalError):
                db._connect_mariadb()


class OpenDbFallbackTests(unittest.TestCase):
    """open_db()'s docstring promises falling back to SQLite (with a
    warning) 'on any problem' -- including a malformed budget.ini, which
    used to crash app startup instead."""

    def test_malformed_ini_falls_back_to_sqlite_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini_path = os.path.join(tmp, "budget.ini")
            with open(ini_path, "w") as f:
                f.write("[database]\nport = not-a-number\n")
            with mock.patch.object(ba, "DB_PATH", os.path.join(tmp, "budget.db")):
                db, warning = ba.open_db(ini_path)
            self.addCleanup(db.conn.close)
            self.assertIsNotNone(warning)
            self.assertIn("budget.ini", warning)
            self.assertEqual(db.config.backend, "sqlite")

    def test_mariadb_requested_without_credentials_falls_back_to_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini_path = os.path.join(tmp, "budget.ini")
            with open(ini_path, "w") as f:
                f.write("[database]\nbackend = mariadb\n")
            with mock.patch.object(ba, "DB_PATH", os.path.join(tmp, "budget.db")):
                db, warning = ba.open_db(ini_path)
            self.addCleanup(db.conn.close)
            self.assertIsNotNone(warning)
            self.assertEqual(db.config.backend, "sqlite")

    def test_no_ini_uses_sqlite_with_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ba, "DB_PATH", os.path.join(tmp, "budget.db")):
                db, warning = ba.open_db(os.path.join(tmp, "no-such.ini"))
            self.addCleanup(db.conn.close)
            self.assertIsNone(warning)
            self.assertEqual(db.config.backend, "sqlite")


if __name__ == "__main__":
    unittest.main()
