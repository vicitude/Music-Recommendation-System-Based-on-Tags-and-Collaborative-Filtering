from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("music", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Rating",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("score", models.PositiveSmallIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("song", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="music.song")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="music.user")),
            ],
            options={"db_table": "music_rating"},
        ),
        migrations.AddConstraint(
            model_name="rating",
            constraint=models.UniqueConstraint(fields=("user", "song"), name="uq_rating_user_song"),
        ),
        migrations.AddConstraint(
            model_name="rating",
            constraint=models.CheckConstraint(condition=models.Q(score__gte=1, score__lte=5), name="ck_rating_score_1_5"),
        ),
        migrations.AddIndex(
            model_name="rating",
            index=models.Index(fields=["song", "score"], name="ix_rating_song_score"),
        ),
    ]
