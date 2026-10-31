from django.db import migrations, models
from django.utils import timezone


def backfill(apps, schema_editor):
    database = schema_editor.connection.alias
    User = apps.get_model('core', 'User')
    Student = apps.get_model('core', 'Student')
    users, students = [], []
    for student in Student.objects.using(database).select_related('user').iterator(chunk_size=500):
        parts = student.user.name.split()
        # Ambiguous legacy names remain intact and can be completed in the account.
        if student.user.first_name or student.user.last_name or len(parts) != (2 if student.no_patronymic else 3):
            continue
        student.user.last_name, student.user.first_name = parts[:2]
        student.patronymic = '' if student.no_patronymic else parts[2]
        users.append(student.user)
        students.append(student)
    User.objects.using(database).bulk_update(users, ['last_name', 'first_name'], batch_size=500)
    Student.objects.using(database).bulk_update(students, ['patronymic'], batch_size=500)
    apps.get_model('core', 'ApiToken').objects.using(database).filter(
        user__roles=['student'], revoked_at=None).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [('core', '0014_material_order_indexes')]
    operations = [
        migrations.AddField(model_name='student', name='patronymic',
                            field=models.CharField(max_length=120, blank=True, default='')),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
