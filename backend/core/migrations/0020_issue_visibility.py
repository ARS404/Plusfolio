from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0019_issue_edit_version')]

    operations = [
        migrations.AddField(
            model_name='worksheetissue', name='visible_to_students',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='worksheetissue', name='visible_to_students',
            field=models.BooleanField(default=False),
        ),
    ]
