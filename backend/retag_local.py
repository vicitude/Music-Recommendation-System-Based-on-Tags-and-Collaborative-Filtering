import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

from seed_local import SeedError, obtain_password, validate_environment
from start_local import StartupError, inspect_database


def main():
    parser = argparse.ArgumentParser(description="仅重标现有40首，不修改歌曲/音频/发布状态")
    parser.add_argument("--apply", action="store_true", help="显式替换40首旧歌曲标签，默认仅预检")
    parser.add_argument("--diagnose", action="store_true", help="仅生成只读歌曲匹配明细，不更新标签")
    parser.add_argument("--plan", type=Path, help="项目local-ai/diagnostics内明确指定的40首计划")
    args = parser.parse_args()
    if args.apply and args.diagnose:
        parser.error("--diagnose不能与--apply同时使用")
    connection = None
    original = {}
    try:
        root = Path(__file__).resolve().parents[1]
        plan_path = args.plan.resolve(strict=True) if args.plan else root / "local-ai/diagnostics/retag40-v2.json"
        if not plan_path.resolve().is_relative_to(root / "local-ai/diagnostics"):
            raise ValueError("计划必须位于项目私有local-ai/diagnostics")
        plan_bytes = plan_path.read_bytes()
        plan = json.loads(plan_bytes)
        expected = validate_environment(os.environ)
        password = obtain_password(os.environ, sys.stdin.isatty())
        values = {**expected, "MYSQL_PASSWORD": password}
        if not os.environ.get("DJANGO_SECRET_KEY"):
            values["DJANGO_SECRET_KEY"] = secrets.token_urlsafe(50)
        for name, value in values.items():
            original[name] = os.environ.get(name)
            os.environ[name] = value
        import django
        django.setup()
        from django.apps import apps
        from django.core.management import call_command
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from music.retag_existing import diagnose_matches, retag_existing
        connection.settings_dict["OPTIONS"]["connect_timeout"] = 5
        call_command("check")
        inspect_database(connection, {model._meta.db_table for model in apps.get_models(include_auto_created=True)} | {"django_migrations"})
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise ValueError("存在待迁移项目，请先完成迁移；本入口不代迁移")
        if args.diagnose:
            diagnosis = diagnose_matches(plan)
            report_path = root / "local-ai/diagnostics" / ("retag-match-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4) + ".json")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with report_path.open("x", encoding="utf-8") as stream:
                json.dump(diagnosis, stream, ensure_ascii=False, indent=2)
            print(f"只读匹配：唯一匹配{diagnosis['matched_unique']}首，缺失{len(diagnosis['missing'])}首，重复{len(diagnosis['duplicates'])}组；库内非目标{len(diagnosis['non_target_songs'])}首")
            for item in diagnosis["missing"]:
                print("未匹配：" + item["filename"])
            for item in diagnosis["duplicates"]:
                print("重复匹配：" + item["filename"] + "；歌曲ID：" + ",".join(str(song["id"]) for song in item["songs"]))
            print("明细已保存：" + str(report_path))
            print("诊断完成，没有修改数据库或歌曲标签")
            return 0
        preview = retag_existing(plan)
        print(json.dumps(preview, ensure_ascii=False))
        if not args.apply:
            print("仅预检，未改任何标签；确认后以--apply执行")
            return 0
        if not sys.stdin.isatty() or input("将替换这40首全部旧标签并保存备份，输入 RETAG 40：") != "RETAG 40":
            raise ValueError("未确认，未写入")
        if hashlib.sha256(plan_path.read_bytes()).digest() != hashlib.sha256(plan_bytes).digest():
            raise ValueError("计划在确认期间已改变")
        backup = root / "local-ai/retag-backups" / ("retag40-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4) + ".json")
        result = retag_existing(plan, apply=True, backup_path=backup)
        check = retag_existing(plan)
        if not check["matches_plan"]:
            raise ValueError("提交后复核不符；请保留备份并检查状态，勿盲目重试")
        print(json.dumps(dict(status="COMMITTED_AND_RECHECKED", result=result, check=check), ensure_ascii=False))
        print("40首标签已提交并复核；音频/发布状态不变，旧标签已备份。主动刷新推荐后使用新标签。")
        return 0
    except (SeedError, StartupError, ValueError, OSError, EOFError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception:
        print("数据库连接或执行失败；未输出密码，请保留备份。若提交后复核失败，先检查数据库状态，不要盲目重试。", file=sys.stderr)
        return 2
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
