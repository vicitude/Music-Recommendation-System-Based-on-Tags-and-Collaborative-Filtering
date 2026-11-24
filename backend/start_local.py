import argparse
import getpass
import os
import secrets
import socket
import sys
import warnings
from pathlib import Path


class StartupError(Exception):
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PASSWORD_FILE = PROJECT_ROOT / "数据库密码.txt"
DEFAULT_SECRET_FILE = PROJECT_ROOT / ".django-secret-key"


def local_audio_environment(environment):
    if environment.get("LOCAL_IMPORT_FFMPEG"):
        return {}
    executable = Path("D:/ffmpeg/ffmpeg.exe")
    return {"LOCAL_IMPORT_FFMPEG": str(executable)} if executable.is_file() else {}


def validate_environment(environment):
    expected = {
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": "3306",
        "MYSQL_DATABASE": "music_recommender_dev",
        "MYSQL_USER": "music_recommender_app",
    }
    for name, value in expected.items():
        if environment.get(name, value) != value:
            raise StartupError(f"{name}不符合已批准的本机专用开发配置，已停止")
    return expected


def obtain_password(environment, interactive):
    password = environment.get("MYSQL_PASSWORD", "")
    password_file = Path(environment.get("MYSQL_PASSWORD_FILE", str(DEFAULT_PASSWORD_FILE))).expanduser()
    if not password and password_file.is_file():
        try:
            lines = password_file.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as error:
            raise StartupError("数据库密码文件无法读取，已停止；请检查本机文件编码和权限") from error
        if len(lines) != 1:
            raise StartupError("数据库密码文件只能包含一行密码，已停止")
        password = lines[0].strip()
    if not password:
        if not interactive:
            raise StartupError("缺少专用数据库密码。请在本机交互终端运行本入口，隐藏输入密码；不要发送到聊天")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                password = getpass.getpass("请输入项目专用数据库账户密码（隐藏输入）：")
            except getpass.GetPassWarning:
                raise StartupError("终端无法安全隐藏输入，已停止；请使用本机交互终端") from None
    if not password or password == "change-me":
        raise StartupError("数据库密码为空或仍为示例值，未尝试连接")
    return password


def obtain_secret_key(environment):
    value = environment.get("DJANGO_SECRET_KEY", "")
    secret_file = Path(environment.get("DJANGO_SECRET_KEY_FILE", str(DEFAULT_SECRET_FILE))).expanduser()
    if value:
        return value
    if secret_file.is_file():
        try:
            value = secret_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            raise StartupError("Django会话密钥文件无法读取，已停止") from error
        if value:
            return value
    value = secrets.token_urlsafe(50)
    temporary = secret_file.with_name("temp_" + secret_file.name)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(value + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, secret_file)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise StartupError("无法保存本机Django会话密钥文件，已停止") from error
    return value


def inspect_database(connection, expected_tables):
    if connection.vendor != "mysql":
        raise StartupError("只允许已批准的MySQL配置，不使用SQLite替代")
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE(), VERSION(), CURRENT_USER(), @@character_set_database, @@session.transaction_isolation")
        database, version, account, charset, isolation = cursor.fetchone()
        if database != "music_recommender_dev" or account.split("@", 1)[0] != "music_recommender_app":
            raise StartupError("实际数据库或登录账户不符合专用范围，已停止")
        if not version.startswith("9.2.") or charset.lower() != "utf8mb4":
            raise StartupError("实际版本或字符集不符合本机MySQL9.2/utf8mb4范围，已停止")
        if isolation.upper() not in {"READ-COMMITTED", "REPEATABLE-READ"}:
            raise StartupError("事务隔离级别不符合要求，已停止")
        cursor.execute("SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")
        tables = dict(cursor.fetchall())
        if set(tables) - set(expected_tables) or any(engine != "InnoDB" for engine in tables.values()):
            raise StartupError("专用库包含非项目表或非InnoDB对象，禁止迁移或覆盖")
        if tables:
            if "django_migrations" not in tables:
                raise StartupError("已有表但缺少项目迁移记录，需人工核对用途")
            cursor.execute("SELECT app, name FROM django_migrations WHERE app = 'music' AND name = '0001_initial'")
            if cursor.fetchone() is None:
                raise StartupError("现有库未确认完成项目初始迁移，停止自动处理")
    return "empty" if not tables else "project"


def ensure_port_available():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            raise StartupError("127.0.0.1:8000已占用或不可绑定；未停止其他进程") from None


def execute_startup(connection, expected_tables, command, executor_factory, *, check_only, create_admin, interactive, confirm=input):
    state = inspect_database(connection, expected_tables)
    print("专用库连接与范围核验通过：" + ("空库" if state == "empty" else "已有项目迁移记录"))
    if check_only:
        print("仅检查完成，未迁移、创建管理员或启动服务")
        return
    ensure_port_available()
    executor = executor_factory(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if pending:
        command("migrate", plan=True, interactive=False)
        if not interactive or confirm("确认仅迁移项目专用库，请输入 APPLY music_recommender_dev：") != "APPLY music_recommender_dev":
            raise StartupError("未确认迁移，未启动后端")
        command("migrate", interactive=False)
    if create_admin:
        if not interactive:
            raise StartupError("创建管理员需本机交互终端，未创建账户")
        command("createsuperuser", interactive=True)
    print("启动本机后端：http://127.0.0.1:8000/admin/；按Ctrl+C停止，不删除数据")
    command("runserver", "127.0.0.1:8000", use_reloader=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="仅项目专用库的安全本机后端启动入口")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check-only", action="store_true")
    group.add_argument("--create-admin", action="store_true")
    args = parser.parse_args(argv)
    original = {}
    connection = None
    try:
        expected = validate_environment(os.environ)
        interactive = sys.stdin.isatty()
        password = obtain_password(os.environ, interactive)
        values = {**expected, **local_audio_environment(os.environ), "MYSQL_PASSWORD": password, "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost"}
        if not os.environ.get("DJANGO_SECRET_KEY"):
            values["DJANGO_SECRET_KEY"] = obtain_secret_key(os.environ)
            print("已加载本机持久化会话密钥，重启后保留管理员登录状态")
        for name, value in values.items():
            original[name] = os.environ.get(name)
            os.environ[name] = value
        import django
        django.setup()
        from django.apps import apps
        from django.core.management import call_command
        from django.db import DatabaseError, connection
        from django.db.migrations.executor import MigrationExecutor
        connection.settings_dict["OPTIONS"]["connect_timeout"] = 5
        call_command("check")
        expected_tables = {model._meta.db_table for model in apps.get_models(include_auto_created=True)} | {"django_migrations"}
        try:
            execute_startup(connection, expected_tables, call_command, MigrationExecutor, check_only=args.check_only, create_admin=args.create_admin, interactive=interactive)
        except DatabaseError as error:
            code = error.args[0] if error.args and isinstance(error.args[0], int) else "unknown"
            raise StartupError(f"数据库连接或操作失败（错误码{code}）。请核对专用账户、密码与库是否已准备；未重试、未改全局配置") from None
        return 0
    except (StartupError, EOFError) as error:
        print(str(error) or "交互输入中断，已停止", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已停止本机后端，不删除数据库或媒体")
        return 0
    finally:
        if connection is not None:
            connection.close()
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    sys.exit(main())
