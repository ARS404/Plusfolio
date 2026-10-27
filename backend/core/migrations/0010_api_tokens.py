import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [('core', '0009_entity_identifiers')]
    operations = [migrations.CreateModel(name='ApiToken', fields=[
        ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
        ('name', models.CharField(max_length=100)),
        ('prefix', models.CharField(max_length=11)),
        ('digest', models.CharField(max_length=64, unique=True, editable=False)),
        ('password_stamp', models.CharField(max_length=64, editable=False)),
        ('read_only', models.BooleanField(default=False)),
        ('created_at', models.DateTimeField(default=timezone.now)),
        ('expires_at', models.DateTimeField(db_index=True)),
        ('revoked_at', models.DateTimeField(null=True)),
        ('last_used_at', models.DateTimeField(null=True)),
        ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name='api_tokens')),
    ])]
