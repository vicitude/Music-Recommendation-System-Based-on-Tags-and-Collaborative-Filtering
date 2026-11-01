import django.contrib.auth.models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Song',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=120)),
                ('artist', models.CharField(max_length=120)),
                ('album', models.CharField(default='', max_length=120)),
                ('duration_ms', models.PositiveIntegerField()),
                ('file_path', models.CharField(default='', max_length=255)),
                ('mime', models.CharField(choices=[('audio/mpeg', 'MP3'), ('audio/wav', 'WAV'), ('audio/ogg', 'OGG')], max_length=10)),
                ('active', models.BooleanField(default=False)),
                ('source_name', models.CharField(max_length=120)),
                ('source_url', models.URLField(max_length=2000)),
                ('license_name', models.CharField(max_length=120)),
                ('license_url', models.URLField(max_length=2000)),
                ('attribution_text', models.TextField(default='')),
                ('checked_at', models.DateTimeField(blank=True, null=True)),
                ('playback_allowed', models.BooleanField(default=False)),
                ('redistribution_allowed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'music_song',
            },
        ),
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('username', models.CharField(max_length=30, unique=True)),
                ('onboarding_completed', models.BooleanField(default=False)),
                ('origin', models.CharField(choices=[('REAL', '真实'), ('SIMULATED', '模拟')], default='REAL', max_length=9)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'db_table': 'music_user',
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Playlist',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'music_playlist',
            },
        ),
        migrations.CreateModel(
            name='Tag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=30)),
                ('kind', models.CharField(choices=[('STYLE', '风格'), ('MOOD', '情绪'), ('SCENE', '场景')], max_length=5)),
                ('active', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'music_tag',
                'constraints': [models.UniqueConstraint(fields=('kind', 'name'), name='uq_tag_kind_name')],
            },
        ),
        migrations.CreateModel(
            name='RecommendationSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField()),
                ('revision', models.PositiveIntegerField(default=1)),
                ('algorithm_version', models.CharField(default='adaptive-v0.1.0', max_length=32)),
                ('alpha_target', models.FloatField()),
                ('alpha_effective', models.FloatField(blank=True, null=True)),
                ('items', models.JSONField(default=list)),
                ('generated_at', models.DateTimeField()),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'music_recommendation_snapshot',
                'constraints': [models.UniqueConstraint(fields=('user', 'day'), name='uq_snapshot_user_day')],
            },
        ),
        migrations.CreateModel(
            name='PlaylistSong',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('playlist', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='music.playlist')),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='music.song')),
            ],
            options={
                'db_table': 'music_playlist_song',
                'constraints': [models.UniqueConstraint(fields=('playlist', 'song'), name='uq_playlist_song')],
            },
        ),
        migrations.CreateModel(
            name='Favorite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='music.song')),
            ],
            options={
                'db_table': 'music_favorite',
                'constraints': [models.UniqueConstraint(fields=('user', 'song'), name='uq_favorite')],
            },
        ),
        migrations.CreateModel(
            name='Behavior',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.UUIDField(unique=True)),
                ('listening_session_id', models.UUIDField()),
                ('kind', models.CharField(choices=[('PLAY', '????'), ('COMPLETE', '????'), ('SKIP', '??')], max_length=8)),
                ('position_ms', models.PositiveIntegerField()),
                ('listened_ms', models.PositiveIntegerField()),
                ('effective_ms', models.PositiveIntegerField()),
                ('occurred_at', models.DateTimeField()),
                ('origin', models.CharField(choices=[('REAL', '真实'), ('SIMULATED', '模拟')], max_length=9)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='music.song')),
            ],
            options={
                'db_table': 'music_behavior',
                'indexes': [models.Index(fields=['user', 'occurred_at'], name='ix_behavior_user_time'), models.Index(fields=['user', 'listening_session_id'], name='ix_behavior_session')],
                'constraints': [models.UniqueConstraint(fields=('user', 'listening_session_id', 'kind'), name='uq_behavior_session_kind')],
            },
        ),
        migrations.CreateModel(
            name='SongTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weight', models.PositiveSmallIntegerField(default=1)),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='music.song')),
                ('tag', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='music.tag')),
            ],
            options={
                'db_table': 'music_song_tag',
                'constraints': [models.UniqueConstraint(fields=('song', 'tag'), name='uq_song_tag')],
            },
        ),
        migrations.CreateModel(
            name='UserTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tag', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='music.tag')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'music_user_tag',
                'constraints': [models.UniqueConstraint(fields=('user', 'tag'), name='uq_user_tag')],
            },
        ),
    ]
