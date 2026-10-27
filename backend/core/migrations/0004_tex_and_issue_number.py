from django.db import migrations, models


def number_existing(apps, schema_editor):
    Issue=apps.get_model('core','WorksheetIssue')
    counters={}
    for issue in Issue.objects.order_by('circle_id','issued_on','pk').iterator():
        counters[issue.circle_id]=counters.get(issue.circle_id,0)+1
        Issue.objects.filter(pk=issue.pk).update(number=counters[issue.circle_id])


class Migration(migrations.Migration):
    dependencies=[('core','0003_student_graduation_year')]
    operations=[
        migrations.AddField(model_name='problem',name='statement_tex',field=models.TextField(blank=True,default='')),
        migrations.AddField(model_name='problem',name='solution_tex',field=models.TextField(blank=True,default='')),
        migrations.AddField(model_name='worksheet',name='template_version',field=models.CharField(max_length=40,default='math-a4-v1')),
        migrations.AddField(model_name='worksheetissue',name='number',field=models.PositiveIntegerField(null=True)),
        migrations.RunPython(number_existing,migrations.RunPython.noop),
        migrations.AlterField(model_name='worksheetissue',name='number',field=models.PositiveIntegerField()),
        migrations.AddConstraint(model_name='worksheetissue',constraint=models.UniqueConstraint(fields=['circle','number'],name='unique_circle_issue_number')),
    ]
