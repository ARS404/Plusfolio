from django.db import migrations,models
import django.db.models.deletion

ENTITIES=[('Circle','CircleNumber'),('Topic','TopicNumber'),('WorksheetDocument','WorksheetNumber'),('Invitation','InvitationNumber')]

def number_existing(apps,schema_editor):
    alias=schema_editor.connection.alias
    for entity,allocator in ENTITIES:
        Model=apps.get_model('core',entity);Number=apps.get_model('core',allocator)
        for pk in Model.objects.using(alias).order_by('pk').values_list('pk',flat=True).iterator():
            Model.objects.using(alias).filter(pk=pk).update(number_id=Number.objects.using(alias).create().pk)

class Migration(migrations.Migration):
    dependencies=[('core','0008_problem_identifiers_and_sources')]
    operations=[
        *[migrations.CreateModel(name=allocator,fields=[('id',models.BigAutoField(primary_key=True,serialize=False))]) for _,allocator in ENTITIES],
        *[migrations.AddField(model_name=entity.lower(),name='number',field=models.OneToOneField(to='core.'+allocator.lower(),null=True,on_delete=django.db.models.deletion.PROTECT,editable=False,related_name=entity.lower())) for entity,allocator in ENTITIES],
        migrations.RunPython(number_existing,migrations.RunPython.noop),
        *[migrations.AlterField(model_name=entity.lower(),name='number',field=models.OneToOneField(to='core.'+allocator.lower(),on_delete=django.db.models.deletion.PROTECT,editable=False,related_name=entity.lower())) for entity,allocator in ENTITIES],
    ]
