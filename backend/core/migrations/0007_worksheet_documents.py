import uuid
from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion


def preserve_library(apps,schema_editor):
    Worksheet=apps.get_model('core','Worksheet')
    Document=apps.get_model('core','WorksheetDocument')
    Issue=apps.get_model('core','WorksheetIssue')
    for sheet in Worksheet.objects.using(schema_editor.connection.alias).all().iterator():
        Document.objects.using(schema_editor.connection.alias).create(
            id=sheet.pk,author_id=sheet.author_id,current_revision_id=sheet.pk,
            public_revision_id=sheet.pk if sheet.published else None)
        Worksheet.objects.using(schema_editor.connection.alias).filter(pk=sheet.pk).update(document_id=sheet.pk)
        Issue.objects.using(schema_editor.connection.alias).filter(worksheet_id=sheet.pk).update(document_id=sheet.pk)


class Migration(migrations.Migration):
    dependencies=[('core','0006_read_path_indexes')]
    operations=[
        migrations.CreateModel(name='WorksheetDocument',fields=[
            ('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('author',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,related_name='worksheet_documents')),
            ('current_revision',models.OneToOneField(to='core.worksheet',null=True,on_delete=django.db.models.deletion.PROTECT,related_name='+')),
            ('public_revision',models.OneToOneField(to='core.worksheet',null=True,on_delete=django.db.models.deletion.PROTECT,related_name='+')),
            ('copied_from',models.ForeignKey(to='core.worksheet',null=True,on_delete=django.db.models.deletion.PROTECT,related_name='copies')),
        ]),
        migrations.AddField(model_name='worksheet',name='document',field=models.ForeignKey(to='core.worksheetdocument',null=True,on_delete=django.db.models.deletion.PROTECT,related_name='revisions')),
        migrations.AddField(model_name='worksheet',name='revision',field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name='worksheetissue',name='document',field=models.ForeignKey(to='core.worksheetdocument',null=True,on_delete=django.db.models.deletion.PROTECT,related_name='issues')),
        migrations.RunPython(preserve_library),
        migrations.AlterField(model_name='worksheet',name='document',field=models.ForeignKey(to='core.worksheetdocument',on_delete=django.db.models.deletion.PROTECT,related_name='revisions')),
        migrations.AlterField(model_name='worksheetissue',name='document',field=models.ForeignKey(to='core.worksheetdocument',on_delete=django.db.models.deletion.PROTECT,related_name='issues')),
        migrations.AddConstraint(model_name='worksheet',constraint=models.UniqueConstraint(fields=['document','revision'],name='unique_worksheet_revision')),
        migrations.RemoveConstraint(model_name='worksheetissue',name='one_issue_per_circle'),
        migrations.AddConstraint(model_name='worksheetissue',constraint=models.UniqueConstraint(fields=['circle','document'],name='one_document_issue_per_circle')),
    ]
