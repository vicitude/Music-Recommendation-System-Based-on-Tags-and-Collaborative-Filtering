import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('music', '0004_comment'),
    ]

    operations = [
        migrations.CreateModel(
            name='Follow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='outgoing_follows', to=settings.AUTH_USER_MODEL)),
                ('target', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='incoming_follows', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'music_follow',
                'indexes': [models.Index(fields=['source', '-created_at', '-id'], name='ix_follow_source_created_id'), models.Index(fields=['target', '-created_at', '-id'], name='ix_follow_target_created_id')],
                'constraints': [models.UniqueConstraint(fields=('source', 'target'), name='uq_follow_source_target'), models.CheckConstraint(condition=models.Q(('source', models.F('target')), _negated=True), name='ck_follow_not_self')],
            },
        ),
    ]
