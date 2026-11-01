from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from start_local import StartupError, execute_startup, inspect_database, obtain_password, validate_environment


class LocalStartupTests(SimpleTestCase):
    def database(self, tables=None, *, version="9.2.0", charset="utf8mb4", account="music_recommender_app@localhost", recorded=True):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            ("music_recommender_dev", version, account, charset, "READ-COMMITTED"),
            ("music", "0001_initial") if recorded else None,
        ]
        cursor.fetchall.return_value = [] if tables is None else tables
        connection = MagicMock(vendor="mysql")
        connection.cursor.return_value.__enter__.return_value = cursor
        return connection

    def test_configuration_rejects_other_database_and_settings(self):
        for environment in ({"MYSQL_DATABASE": "other"}, {"MYSQL_USER": "root"}, {"MYSQL_HOST": "remote"}, {"DJANGO_SETTINGS_MODULE": "config.test_settings"}):
            with self.subTest(environment=environment), self.assertRaises(StartupError):
                validate_environment(environment)
        self.assertEqual(validate_environment({})["MYSQL_DATABASE"], "music_recommender_dev")

    def test_noninteractive_missing_password_never_prompts(self):
        with patch("start_local.getpass.getpass") as prompt, self.assertRaises(StartupError):
            obtain_password({}, False)
        prompt.assert_not_called()

    def test_empty_and_example_password_are_rejected(self):
        for password in ("", "change-me"):
            with patch("start_local.getpass.getpass", return_value=password), self.assertRaises(StartupError):
                obtain_password({"MYSQL_PASSWORD": password}, True)

    def test_interactive_password_not_saved_to_environment(self):
        environment = {}
        with patch("start_local.getpass.getpass", return_value="test-only-value"):
            self.assertEqual(obtain_password(environment, True), "test-only-value")
        self.assertEqual(environment, {})

    def test_database_empty_or_owned_migrated_tables_allowed(self):
        self.assertEqual(inspect_database(self.database(), {"django_migrations", "music_user"}), "empty")
        self.assertEqual(inspect_database(self.database([("django_migrations", "InnoDB"), ("music_user", "InnoDB")]), {"django_migrations", "music_user"}), "project")

    def test_nonproject_tables_and_partial_migration_stop(self):
        for tables, recorded in (([("other_table", "InnoDB")], True), ([("music_user", "InnoDB")], True), ([("django_migrations", "InnoDB")], False), ([("music_user", "MyISAM")], True)):
            with self.subTest(tables=tables, recorded=recorded), self.assertRaises(StartupError):
                inspect_database(self.database(tables, recorded=recorded), {"django_migrations", "music_user"})

    def test_version_charset_and_account_must_match_scope(self):
        for options in ({"version": "8.0.0"}, {"charset": "latin1"}, {"account": "root@localhost"}):
            with self.subTest(options=options), self.assertRaises(StartupError):
                inspect_database(self.database(**options), set())

    def executor(self, pending):
        executor = MagicMock()
        executor.migration_plan.return_value = [SimpleNamespace()] if pending else []
        return MagicMock(return_value=executor)

    def test_check_only_never_migrates_or_starts(self):
        command = MagicMock()
        execute_startup(self.database(), set(), command, self.executor(True), check_only=True, create_admin=False, interactive=False)
        command.assert_not_called()

    def test_pending_migration_requires_exact_interactive_confirmation(self):
        command = MagicMock()
        with patch("start_local.ensure_port_available"), self.assertRaises(StartupError):
            execute_startup(self.database(), set(), command, self.executor(True), check_only=False, create_admin=False, interactive=True, confirm=lambda _: "no")
        self.assertEqual([call.args[0] for call in command.call_args_list], ["migrate"])
        self.assertTrue(command.call_args.kwargs["plan"])

    def test_confirmed_migration_then_admin_then_local_only_server(self):
        command = MagicMock()
        with patch("start_local.ensure_port_available"):
            execute_startup(self.database(), set(), command, self.executor(True), check_only=False, create_admin=True, interactive=True, confirm=lambda _: "APPLY music_recommender_dev")
        self.assertEqual([call.args[0] for call in command.call_args_list], ["migrate", "migrate", "createsuperuser", "runserver"])
        self.assertEqual(command.call_args.args, ("runserver", "127.0.0.1:8000"))
        self.assertFalse(command.call_args.kwargs["use_reloader"])

    def test_existing_migration_starts_without_mutation(self):
        command = MagicMock()
        with patch("start_local.ensure_port_available"):
            execute_startup(self.database(), set(), command, self.executor(False), check_only=False, create_admin=False, interactive=False)
        self.assertEqual([call.args[0] for call in command.call_args_list], ["runserver"])

    def test_busy_port_stops_before_migration(self):
        command = MagicMock()
        with patch("start_local.ensure_port_available", side_effect=StartupError("busy")), self.assertRaises(StartupError):
            execute_startup(self.database(), set(), command, self.executor(True), check_only=False, create_admin=False, interactive=True)
        command.assert_not_called()
