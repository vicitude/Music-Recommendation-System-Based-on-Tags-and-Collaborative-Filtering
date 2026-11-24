import os
import sys

from start_local import StartupError, inspect_database, obtain_password, obtain_secret_key, validate_environment


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-confirmed", action="store_true")
    parser.add_argument("--evaluate-output")
    args = parser.parse_args()
    original = {}
    connection = None
    try:
        values = {**validate_environment(os.environ), "MYSQL_PASSWORD": obtain_password(os.environ, sys.stdin.isatty()), "DJANGO_SECRET_KEY": obtain_secret_key(os.environ)}
        for name, value in values.items():
            original[name] = os.environ.get(name)
            os.environ[name] = value
        import django
        django.setup()
        from django.apps import apps
        from django.db import connection
        from django.db.models import Count
        from music.models import Behavior, Favorite, Rating, Song, Tag, User, UserTag
        from music.simulation_profiles import ARCHETYPES, formal_tags
        connection.settings_dict["OPTIONS"]["connect_timeout"] = 5
        inspect_database(connection, {model._meta.db_table for model in apps.get_models(include_auto_created=True)} | {"django_migrations"})
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise StartupError("存在未执行迁移，停止C1操作")
        if args.apply_confirmed:
            from django.core.management import call_command
            call_command("prepare_c1_simulation", confirm="C1 ADD 200")
        if args.evaluate_output:
            from django.core.management import call_command
            call_command("evaluate_c1_dataset", output=args.evaluate_output)
        import json
        report = dict(mode="READ_ONLY", accounts=list(User.objects.values("origin").annotate(count=Count("id"))), c1_accounts=User.objects.filter(username__startswith="sim_c1_").count(), published_songs=Song.objects.filter(active=True).count(), active_tags=Tag.objects.filter(active=True).count(), formal_tags={kind: len(tags) for kind, tags in formal_tags().items()}, simulated_behaviors=Behavior.objects.filter(origin="SIMULATED").count(), simulated_favorites=Favorite.objects.filter(user__origin="SIMULATED").count(), simulated_ratings=Rating.objects.filter(user__origin="SIMULATED").count())
        available = formal_tags()
        report["profile_gaps"] = [dict(profile=profile[0], missing_kinds=[kind for kind, names in zip((Tag.STYLE, Tag.MOOD, Tag.SCENE), profile[1:]) if not any(name in available[kind] for name in names)]) for profile in ARCHETYPES if any(not any(name in available[kind] for name in names) for kind, names in zip((Tag.STYLE, Tag.MOOD, Tag.SCENE), profile[1:]))]
        from collections import Counter
        from zoneinfo import ZoneInfo
        from django.utils import timezone
        from music.recommendation import time_context
        from music.diagnostics import build_diagnostics
        users = list(User.objects.filter(origin="SIMULATED", username__startswith="sim_c1_").order_by("id"))
        report["time_context_plays"] = dict(Counter(time_context(hour=stamp.astimezone(ZoneInfo("Asia/Shanghai")).hour) for stamp in Behavior.objects.filter(user__in=users, kind=Behavior.PLAY).values_list("occurred_at", flat=True)))
        report["distinct_interest_sets"] = len({tuple(UserTag.objects.filter(user=user).order_by("tag_id").values_list("tag_id", flat=True)) for user in users})
        report["diagnostic_sample"] = []
        for user in users[:8]:
            result = build_diagnostics(user_id=user.pk, now=timezone.now())
            report["diagnostic_sample"].append(dict(account=user.username, rows=len(result["rows"]), positive_count=result["positive_count"], route_weights=result["route_weights"]))
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception:
        print("C1操作未完成：请检查专用数据库、迁移、既有模拟账号和正式标签。若写入事务失败已回滚；勿盲目重复执行。", file=sys.stderr)
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
