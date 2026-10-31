from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def count_existing_mail(apps,schema_editor):
    zone=ZoneInfo(settings.TIME_ZONE)
    day=timezone.localdate(timezone=zone)
    start=datetime.combine(day,time.min,zone)
    used=apps.get_model('core','EmailOutbox').objects.using(schema_editor.connection.alias).filter(
        state='sent',sent_at__gte=start,sent_at__lt=start+timedelta(days=1)).count()
    apps.get_model('core','MailBudget').objects.using(schema_editor.connection.alias).create(pk=1,day=day,used=used)


class Migration(migrations.Migration):
    dependencies=[('core','0015_student_name_parts')]
    operations=[
        migrations.CreateModel(name='MailBudget',fields=[
            ('id',models.PositiveSmallIntegerField(default=1,editable=False,primary_key=True,serialize=False)),
            ('daily_limit',models.PositiveIntegerField(default=100)),
            ('day',models.DateField(null=True)),('used',models.PositiveIntegerField(default=0))],
            options={'constraints':[models.CheckConstraint(condition=models.Q(id=1),name='one_mail_budget')]}),
        migrations.RunPython(count_existing_mail,migrations.RunPython.noop),
    ]
