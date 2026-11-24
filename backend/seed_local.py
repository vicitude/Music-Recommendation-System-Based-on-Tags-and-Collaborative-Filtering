import argparse
import getpass
import os
import secrets
import sys
import warnings


class SeedError(Exception):
    pass


EXPECTED = {
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "MYSQL_HOST": "127.0.0.1",
    "MYSQL_PORT": "3306",
    "MYSQL_DATABASE": "music_recommender_dev",
    "MYSQL_USER": "music_recommender_app",
}


def validate_environment(environment):
    for name, value in EXPECTED.items():
        if environment.get(name, value) != value:
            raise SeedError(f"{name}不符合已批准的本机专用开发配置，已停止")
    return dict(EXPECTED)


def obtain_password(environment, interactive):
    password = environment.get("MYSQL_PASSWORD", "")
    if not password:
        if not interactive:
            raise SeedError("缺少专用数据库密码。请在本机交互终端运行本入口，隐藏输入密码；不要发送到聊天")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                password = getpass.getpass("请输入项目专用数据库账户密码（隐藏输入）：")
            except getpass.GetPassWarning:
                raise SeedError("终端无法安全隐藏输入，已停止；请使用本机交互终端") from None
    if not password or password == "change-me":
        raise SeedError("数据库密码为空或仍为示例值，未尝试连接")
    return password


def inspect_database(connection):
    if connection.vendor != "mysql":
        raise SeedError("只允许已批准的MySQL配置，不使用SQLite替代")
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE(), VERSION(), CURRENT_USER(), @@character_set_database")
        database, version, account, charset = cursor.fetchone()
        if database != "music_recommender_dev" or account.split("@", 1)[0] != "music_recommender_app":
            raise SeedError("实际数据库或登录账户不符合专用范围，已停止")
        if not version.startswith("9.2.") or charset.lower() != "utf8mb4":
            raise SeedError("实际版本或字符集不符合本机MySQL9.2/utf8mb4范围，已停止")
        cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")
        if cursor.fetchone()[0] == 0:
            raise SeedError("专用库为空，尚未完成项目迁移；请先运行后端启动入口完成迁移")
    return database


def main(argv=None):
    parser = argparse.ArgumentParser(description="仅向项目专用库写入模拟用户与行为的本机入口")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile-version", choices=["legacy", "formal-v1"], default="legacy")
    parser.add_argument("--username-prefix", default="sim_user_")
    parser.add_argument("--login-password", default="", help="可选：设置本地模拟账号的统一登录口令")
    parser.add_argument("--check-only", action="store_true", help="只核验专用库与曲库状态，不写入任何数据")
    args = parser.parse_args(argv)
    if args.count < 1 or args.count > 10000:
        print("count 必须在 1 到 10000 之间", file=sys.stderr)
        return 2
    original = {}
    connection = None
    try:
        expected = validate_environment(os.environ)
        interactive = sys.stdin.isatty()
        password = obtain_password(os.environ, interactive)
        values = {**expected, "MYSQL_PASSWORD": password, "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost"}
        if not os.environ.get("DJANGO_SECRET_KEY"):
            values["DJANGO_SECRET_KEY"] = secrets.token_urlsafe(50)
        for name, value in values.items():
            original[name] = os.environ.get(name)
            os.environ[name] = value
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import DatabaseError, connection
        from django.db.migrations.executor import MigrationExecutor
        from music.models import Song, User
        connection.settings_dict["OPTIONS"]["connect_timeout"] = 5
        call_command("check")
        inspect_database(connection)
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            names = ", ".join(f"{migration.app}.{migration.name}" for migration, _ in pending)
            raise SeedError(f"专用库存在未执行的迁移（{names}），请先运行 backend\\start_local.py 完成迁移后再导入模拟数据")
        active_songs = Song.objects.filter(active=True).count()
        simulated_users = User.objects.filter(origin="SIMULATED").count()
        real_users = User.objects.filter(origin="REAL").count()
        print(f"专用库核验通过；当前已发布（active）歌曲 {active_songs} 首")
        print(f"当前账号：真实 {real_users} 个，模拟 {simulated_users} 个")
        if active_songs == 0:
            raise SeedError("没有已发布歌曲，模拟数据无法产生推荐，先在后台发布歌曲")
        if args.check_only:
            print("仅检查完成，未写入任何模拟数据")
            return 0
        print(f"开始写入模拟数据：用户 {args.count} 个，种子 {args.seed}，标记 origin=SIMULATED")
        call_command(
            "seed_simulated_users",
            count=args.count,
            seed=args.seed,
            profile_version=args.profile_version,
            username_prefix=args.username_prefix,
            login_password=args.login_password,
            verbosity=1,
        )
        print("模拟数据写入完成；未删除任何既有账号、歌曲或媒体文件")
        return 0
    except (SeedError, EOFError) as error:
        print(str(error) or "交互输入中断，已停止", file=sys.stderr)
        return 2
    except DatabaseError:
        print("数据库连接或操作失败。请核对专用账户、密码与库是否已准备；未重试、未改全局配置", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已停止，未写入任何数据")
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
