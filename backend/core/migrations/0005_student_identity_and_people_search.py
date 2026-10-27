import unicodedata
from django.db import migrations,models


def populate_search(apps,schema_editor):
    User=apps.get_model('core','User')
    for user in User.objects.all().iterator():
        value=' '.join(unicodedata.normalize('NFKC',user.name).casefold().replace('ё','е').split())
        User.objects.filter(pk=user.pk).update(name_search=value)


class Migration(migrations.Migration):
    dependencies=[('core','0004_tex_and_issue_number')]
    operations=[
        migrations.AddField(model_name='user',name='name_search',field=models.CharField(max_length=240,default='',editable=False,db_index=True)),
        migrations.AddField(model_name='student',name='no_patronymic',field=models.BooleanField(default=False)),
        migrations.RunPython(populate_search,migrations.RunPython.noop),
    ]
