import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("music", "0003_recommendation_scene")]

    operations = [
        migrations.CreateModel(
            name="Comment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content", models.CharField(max_length=500, verbose_name="评论内容")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="发表时间")),
                ("song", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="music.song", verbose_name="歌曲")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name="作者")),
            ],
            options={
                "db_table": "music_comment", "verbose_name": "歌曲评论", "verbose_name_plural": "歌曲评论",
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["song", "-created_at", "-id"], name="ix_comment_song_created_id")],
            },
        ),
    ]
