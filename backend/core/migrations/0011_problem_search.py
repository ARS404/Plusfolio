import django.db.models.deletion
from django.db import migrations, models
from pgvector.django import VectorExtension, VectorField


def indexes(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        schema_editor.execute('CREATE INDEX problem_search_text_trgm ON core_problemsearchdocument USING gin (normalized gin_trgm_ops)')
        schema_editor.execute('CREATE INDEX problem_search_hnsw ON core_problemsearchdocument USING hnsw (embedding vector_cosine_ops)')


def remove_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('DROP INDEX IF EXISTS problem_search_text_trgm')
        schema_editor.execute('DROP INDEX IF EXISTS problem_search_hnsw')


class Migration(migrations.Migration):
    dependencies = [('core', '0010_api_tokens')]
    operations = [
        VectorExtension(),
        migrations.CreateModel(name='ProblemSearchDocument', fields=[
            ('id', models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name='ID')),
            ('kind', models.CharField(max_length=12, choices=[('statement', 'statement'), ('solution', 'solution')])),
            ('text', models.TextField()), ('normalized', models.TextField()),
            ('fingerprint', models.CharField(max_length=64)),
            ('embedding', VectorField(dimensions=384, null=True)),
            ('model', models.CharField(max_length=100, default='')),
            ('indexed_at', models.DateTimeField(null=True)), ('retry_at', models.DateTimeField(null=True)),
            ('problem', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='search_documents', to='core.problem')),
        ], options={
            'constraints': [models.UniqueConstraint(fields=['problem', 'kind'], name='one_problem_search_section')],
            'indexes': [models.Index(fields=['model', 'kind'], name='search_model_kind')],
        }),
        migrations.RunPython(indexes, remove_indexes),
    ]
