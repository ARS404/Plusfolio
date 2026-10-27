from django.db import migrations,models
import django.db.models.deletion


def number_existing(apps,schema_editor):
    Problem=apps.get_model('core','Problem');Number=apps.get_model('core','ProblemNumber')
    alias=schema_editor.connection.alias
    for problem in Problem.objects.using(alias).order_by('created_at','pk').iterator():
        number=Number.objects.using(alias).create()
        Problem.objects.using(alias).filter(pk=problem.pk).update(number_id=number.pk)


class Migration(migrations.Migration):
    dependencies=[('core','0007_worksheet_documents')]
    operations=[
        migrations.CreateModel(name='ProblemNumber',fields=[('id',models.BigAutoField(primary_key=True,serialize=False))]),
        migrations.AlterField(model_name='problem',name='title',field=models.CharField(max_length=180,blank=True,default='')),
        migrations.AddField(model_name='problem',name='number',field=models.OneToOneField(to='core.problemnumber',null=True,on_delete=django.db.models.deletion.PROTECT,editable=False,related_name='problem')),
        migrations.AddField(model_name='problem',name='source',field=models.CharField(max_length=40,blank=True,default='')),
        migrations.AddField(model_name='problem',name='source_id',field=models.CharField(max_length=64,blank=True,default='')),
        migrations.AddField(model_name='problem',name='source_url',field=models.URLField(max_length=400,blank=True,default='')),
        migrations.AddField(model_name='problem',name='source_metadata',field=models.JSONField(default=dict,blank=True)),
        migrations.RunPython(number_existing,migrations.RunPython.noop),
        migrations.AlterField(model_name='problem',name='number',field=models.OneToOneField(to='core.problemnumber',on_delete=django.db.models.deletion.PROTECT,editable=False,related_name='problem')),
        migrations.AddConstraint(model_name='problem',constraint=models.UniqueConstraint(fields=['source','source_id'],condition=~models.Q(source='')&~models.Q(source_id=''),name='unique_external_problem')),
    ]
