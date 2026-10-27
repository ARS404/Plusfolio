"""Validate and import an immutable, attributable problems.ru sample by source IDs."""
import hashlib,json,re,uuid
from pathlib import Path
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import Problem,Topic,TopicCatalogVersion
from . import services as s


def topic_uuid(identifier):return uuid.uuid5(uuid.NAMESPACE_URL,'plusfolio-topic:'+identifier)
def problem_uuid(identifier):return uuid.uuid5(uuid.NAMESPACE_URL,'https://problems.ru/view_problem_details_new.php?id='+identifier)


def validate(data):
    if data.get('schema_version')!=1 or data.get('source')!='problems.ru':raise ValidationError('Неизвестный формат импорта.')
    rows=data.get('problems')
    if not isinstance(rows,list) or not rows or len(rows)>10000:raise ValidationError('В импорте должно быть от 1 до 10000 задач.')
    identifiers=set()
    for row in rows:
        identifier=row.get('source_id')
        if not isinstance(identifier,str) or not re.fullmatch(r'[1-9]\d{0,11}',identifier) or identifier in identifiers:raise ValidationError('Некорректный или повторный исходный номер задачи.')
        identifiers.add(identifier)
        if row.get('source_url')!='https://problems.ru/view_problem_details_new.php?id='+identifier:raise ValidationError('Ссылка на источник не соответствует номеру задачи.')
        for field in ['statement','solution']:
            if not isinstance(row.get(field),str) or not row[field].strip() or len(row[field])>30000:raise ValidationError('Пустой или слишком длинный текст задачи.')
        if len(row.get('title',''))>180:raise ValidationError('Название задачи слишком длинное.')
        checksum=hashlib.sha256((row['statement']+'\n\n'+row['solution']).encode()).hexdigest()
        if row.get('content_sha256')!=checksum:raise ValidationError('Контрольная сумма задачи не совпала.')
        if not isinstance(row.get('topics'),list) or not row['topics']:raise ValidationError('У задачи отсутствуют темы.')
        if any(not isinstance(topic.get('id'),str) or not topic['id'].isdigit() for topic in row['topics']):raise ValidationError('Некорректный номер темы.')
    return rows


@transaction.atomic
def import_sample(user,data,catalog,*,dry_run=False):
    s.require(s.admin(user),'Импорт задач доступен только администратору.')
    rows=validate(data)
    if catalog.get('conflicts'):raise ValidationError('В исходном дереве тем есть конфликты.')
    nodes={row['id']:row for row in catalog['normalized_nodes']}
    source_nodes={str(row['source_id']):row for row in nodes.values() if row.get('source_id')}
    existing={problem.source_id:problem for problem in Problem.objects.filter(source='problems.ru',source_id__in=[row['source_id'] for row in rows])}
    incoming=[]
    for row in rows:
        problem=existing.get(row['source_id'])
        if problem:
            if (problem.statement,problem.solution)!=(row['statement'],row['solution']):raise ValidationError('Источник задачи '+row['source_id']+' изменился; опубликованная задача не перезаписана.')
        else:incoming.append(row)
    for row in rows:
        for topic in row['topics']:
            if topic['id']!='1' and topic['id'] not in source_nodes:raise ValidationError('Обновите каталог тем: исходная тема '+topic['id']+' пока не описана.')
    if dry_run:return {'created':len(incoming),'skipped':len(rows)-len(incoming),'topics_created':0,'dry_run':True}
    # Stable external IDs preserve admin renames/moves and never match by the visible name.
    by_source={topic.source_id:topic for topic in Topic.objects.exclude(source_id='')}
    by_id={str(topic.pk):topic for topic in Topic.objects.all()};created_topics=[]
    def ensure(node_id):
        node=nodes[node_id];source_id=str(node.get('source_id') or '')
        found=by_source.get(source_id) if source_id else None
        found=found or by_id.get(str(topic_uuid(node_id)))
        if found:return found
        parent=ensure(node['parent_id']) if node['parent_id'] else None
        topic=Topic.objects.create(id=topic_uuid(node_id),name=node['name'],parent=parent,source_id=source_id,is_other=node['is_other'],sort_order=node.get('sort_order',0))
        by_id[str(topic.pk)]=topic
        if source_id:by_source[source_id]=topic
        created_topics.append(topic.pk)
        if not node['is_other']:
            other=next((value for value in nodes.values() if value['parent_id']==node_id and value['is_other']),None)
            if other:ensure(other['id'])
        return topic
    task_topics={}
    for row in incoming:
        selected=[]
        for topic in row['topics']:
            # The source's technical "Undefined" is our existing root Other category.
            node=nodes['other:problems:1302'] if topic['id']=='1' else source_nodes[topic['id']]
            selected.append(ensure(node['id']))
        if any(topic.archived or not s.topic_active(topic) for topic in selected):raise ValidationError('Одна из исходных тем в архиве; решение администратора не изменено.')
        task_topics[row['source_id']]=list({topic.pk for topic in selected})
    if created_topics:s.snapshot_topics()
    version=TopicCatalogVersion.objects.order_by('-pk').values_list('pk',flat=True).first()
    problems=[Problem(id=problem_uuid(row['source_id']),title=row.get('title','').strip(),statement=row['statement'],solution=row['solution'],author=user,
        source='problems.ru',source_id=row['source_id'],source_url=row['source_url'],topic_catalog_version_id=version,
        source_metadata={'fetched_at':data.get('fetched_at'),'content_sha256':row['content_sha256'],'topics':row['topics'],
            'catalog_subjects':row.get('catalog_subjects',[]),'has_detailed_solution':row.get('has_detailed_solution',False),
            'difficulty':row.get('difficulty',''),'grades':row.get('grades',[]),'copyright_url':data.get('copyright_url')}) for row in incoming]
    Problem.objects.bulk_create(problems)
    Problem.topics.through.objects.bulk_create([Problem.topics.through(problem=problem,topic_id=topic) for problem in problems for topic in task_topics[problem.source_id]])
    Problem.objects.filter(pk__in=[problem.pk for problem in problems]).update(published=True)
    if problems:s.audit(user,'problem.import',{'source':'problems.ru','created':len(problems),'topics_created':len(created_topics)})
    return {'created':len(problems),'skipped':len(rows)-len(problems),'topics_created':len(created_topics),'dry_run':False}
