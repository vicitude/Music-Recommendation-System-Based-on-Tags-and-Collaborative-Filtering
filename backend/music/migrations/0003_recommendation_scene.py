from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("music", "0002_rating")]

    operations = [
        migrations.AddField(
            model_name="recommendationsnapshot",
            name="route_weights",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="recommendationsnapshot",
            name="scene_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="recommendationsnapshot",
            name="scene_source",
            field=models.CharField(blank=True, default="", max_length=4),
        ),
        migrations.AddField(
            model_name="recommendationsnapshot",
            name="scene_match_rate",
            field=models.FloatField(default=0),
        ),
    ]
